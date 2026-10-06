"""CISO.ai course edition: one user, one workflow, one AI capability."""
import copy
import base64
from pathlib import Path
from datetime import date, datetime, timezone
import json
import os
import time
import streamlit as st
from ai_client import AIError, CallBudget, generate_plan
from core import (CRITICALITIES, EXPOSURES, PRIORITIES, SEVERITIES, ValidationError,
                  export_csv, fingerprint, privacy_flags, validate_input, validate_plan)
from session_io import (CSV_FIELDS, STATUSES, action_rows, csv_template, default_tracking,
                        make_session, parse_csv, parse_session, validate_tracking)
from word_export import export_docx
from governance import (CATALOG, ASSESSMENTS, DECISIONS, NOTICE, ALIGNMENT_NOTICE,
                        NIST_SOURCE, CIS_SOURCE, default_alignment, validate_alignment, create_signoff, current_signoff)

st.set_page_config(page_title='CISO.ai | Remediation planner', page_icon='🛡️', layout='wide')


def setting(name, default=''):
    try:
        return str(st.secrets.get(name, os.environ.get(name, default)))
    except FileNotFoundError:
        return os.environ.get(name, default)


@st.cache_resource
def budget():
    return CallBudget()  # Only counters shared; never user inputs or outputs.


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def brand_logo(width):
    logo = Path(__file__).resolve().parent / 'assets' / 'logo.png'
    if logo.is_file():
        encoded = base64.b64encode(logo.read_bytes()).decode('ascii')
        st.markdown(f'<div style="background:#13263c;border-radius:12px;padding:12px 16px;margin-bottom:16px;max-width:{width}px"><img alt="CISO.ai Security Operating System" style="display:block;width:100%;height:auto" src="data:image/png;base64,{encoded}"></div>', unsafe_allow_html=True)
    else:
        st.markdown('**CISO.ai**')


def reset_plan():
    for key in list(st.session_state):
        if key.startswith(('review_', 'track_', 'align_', 'sign_')) or key in ('alignment', 'record', 'reviewed', 'confirmed', 'editor_cache', 'tracking', 'filter_priority', 'filter_status'):
            del st.session_state[key]


def clear_session():
    last = st.session_state.get('last_call', 0)
    for key in list(st.session_state):
        del st.session_state[key]
    st.session_state['last_call'] = last


def set_findings(rows):
    for i in range(5):
        for field in CSV_FIELDS:
            st.session_state.pop(f'{field}_{i}', None)
    st.session_state['count'] = len(rows)
    for i, row in enumerate(rows):
        for field in CSV_FIELDS:
            st.session_state[f'{field}_{i}'] = row[field]


def capture_upload(widget_key, bytes_key):
    uploaded = st.session_state.get(widget_key)
    st.session_state[bytes_key] = uploaded.getvalue() if uploaded is not None else None


def import_findings():
    uploaded = st.session_state.get('csv_bytes')
    try:
        if uploaded is None:
            raise ValidationError('Choose a CSV file first.')
        rows = parse_csv(uploaded)
        reset_plan()
        set_findings(rows)
        st.session_state['consent'] = False
        st.session_state['import_notice'] = ('success', 'Findings imported. Review them and confirm sharing before generation.')
    except (ValidationError, TypeError, KeyError, AttributeError) as exc:
        st.session_state['import_notice'] = ('error', str(exc) if isinstance(exc, ValidationError) else 'Invalid CSV file. Existing work was kept.')


def apply_session(workspace):
    # Called only after full file validation, before input widgets are created.
    reset_plan()
    set_findings(workspace['input']['findings'])
    st.session_state['context'] = workspace['input']['business_context']
    st.session_state['constraints'] = workspace['input']['constraints']
    st.session_state['consent'] = False
    if workspace['record']:
        st.session_state['record'] = workspace['record']
        st.session_state['editor_cache'] = workspace['editor_plan']
        st.session_state['tracking'] = workspace['tracking']
        st.session_state['alignment'] = workspace['alignment']
    st.session_state['confirmed'] = False


def restore_session():
    uploaded = st.session_state.get('session_bytes')
    try:
        if uploaded is None:
            raise ValidationError('Choose a session JSON file first.')
        workspace = parse_session(uploaded)
        apply_session(workspace)
        st.session_state['import_notice'] = ('success', 'Session restored as a draft. Check the data and confirm review and sign off again before exporting a decision.')
    except (ValidationError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        st.session_state['import_notice'] = ('error', str(exc) if isinstance(exc, ValidationError) else 'Invalid session file. Existing work was kept.')


def review_plan(record):
    st.divider()
    st.subheader('2 · Review and assign actions')
    if record['provenance'].startswith('Imported'):
        st.info('This is an imported draft. The file’s origin and previous review cannot be verified by this app.')
    st.caption('Owner, target date and status are entered by you. They are not sent to Gemini. Completed is your reported status, not an independent verification.')
    cached = st.session_state.get('editor_cache', record['original_ai_plan'])
    tracking = st.session_state.get('tracking', default_tracking(cached))
    original = {row['finding_id']: row for row in record['original_ai_plan']['items']}
    alignment = st.session_state.get('alignment', default_alignment(cached))
    st.caption(ALIGNMENT_NOTICE)
    st.markdown(f'[NIST CSF 2.0 source]({NIST_SOURCE}) · [CIS Controls v8.1 source]({CIS_SOURCE})')
    edited_alignment = {}
    edited_items, edited_tracking = [], {}
    for item in cached['items']:
        fid = item['finding_id']
        source = next(row for row in record['input']['findings'] if row['finding_id'] == fid)
        with st.expander(f"{fid} · {source['asset']}", expanded=True):
            st.caption('Submitted observation')
            st.text(source['observation'])
            with st.expander('Original AI draft'):
                st.json(original[fid])
            priority = st.selectbox('Priority', PRIORITIES, index=PRIORITIES.index(item['priority']), key=f'review_{fid}_priority')
            edited = dict(finding_id=fid, priority=priority)
            for field, label in [('rationale', 'Why this priority?'), ('action', 'Proposed action'),
                                 ('verification', 'How to verify the outcome'), ('uncertainty', 'Assumptions and unknowns')]:
                edited[field] = st.text_area(label, value=item[field], max_chars=1800, key=f'review_{fid}_{field}')
            a, b, c = st.columns(3)
            owner = a.text_input('Owner role or alias', value=tracking[fid]['owner'], max_chars=80, key=f'track_{fid}_owner')
            saved_date = date.fromisoformat(tracking[fid]['target_date']) if tracking[fid]['target_date'] else None
            target = b.date_input('Target date (optional)', value=saved_date, min_value=date(1900, 1, 1), max_value=date(2100, 12, 31), key=f'track_{fid}_date')
            status = c.selectbox('Action status', STATUSES, index=STATUSES.index(tracking[fid]['status']), key=f'track_{fid}_status')
            edited_tracking[fid] = dict(owner=owner, target_date=target.isoformat() if target else '', status=status)
            with st.expander('Standards alignment · human review'):
                saved = alignment[fid]
                refs = st.multiselect('Applicable references', list(CATALOG), default=saved['references'], format_func=lambda r: f'{r} · {CATALOG[r]}', key=f'align_{fid}_refs')
                assessment = st.selectbox('Alignment assessment', ASSESSMENTS, index=ASSESSMENTS.index(saved['assessment']), key=f'align_{fid}_assessment')
                reason = st.text_area('Why these references apply', value=saved['rationale'], max_chars=1800, key=f'align_{fid}_reason')
                evidence = st.text_area('Sanitized evidence reference or verification note', value=saved['evidence'], max_chars=1000, key=f'align_{fid}_evidence', help='Use aliases or document IDs. Do not paste confidential evidence or credentials.')
                edited_alignment[fid] = dict(references=refs, assessment=assessment, rationale=reason, evidence=evidence)
            edited_items.append(edited)
    edited_plan = {'items': edited_items}
    st.session_state['editor_cache'] = edited_plan
    st.session_state['tracking'] = edited_tracking
    st.session_state['alignment'] = edited_alignment
    st.markdown('**Action overview**')
    left, middle, right = st.columns(3)
    left.metric('Actions', len(edited_items))
    middle.metric('Urgent or high', sum(row['priority'] in ('Urgent', 'High') for row in edited_items))
    right.metric('Reported completed', sum(row['status'] == 'Completed' for row in edited_tracking.values()))
    a, b = st.columns(2)
    priorities = a.multiselect('Filter overview by priority', PRIORITIES, key='filter_priority')
    statuses = b.multiselect('Filter overview by status', STATUSES, key='filter_status')
    visible = action_rows(edited_plan, edited_tracking, record['input'], priorities, statuses)
    st.caption(f'{len(visible)} of {len(edited_items)} actions shown. Filters affect this overview only; review and exports include every action.')
    if visible:
        st.dataframe(visible, hide_index=True, width='stretch')
    else:
        st.info('No actions match these filters. Clear a filter to see more.')
    edited_fingerprint = fingerprint({'plan': edited_plan, 'tracking': edited_tracking, 'alignment': edited_alignment})
    confirmed = st.checkbox('I have reviewed all priorities, actions, assignments and assumptions, including operational impact.', key='confirmed')
    previous = st.session_state.get('reviewed')
    if previous and (not confirmed or previous['editor_fingerprint'] != edited_fingerprint):
        previous.pop('signoff', None)
    if st.button('Confirm review and prepare export', type='primary'):
        try:
            if not confirmed:
                raise ValidationError('Confirm that you reviewed the draft first.')
            accepted = validate_plan(edited_plan, record['input'])
            checked_tracking = validate_tracking(edited_tracking, accepted)
            checked_alignment = validate_alignment(edited_alignment, accepted, final=True)
            st.session_state['reviewed'] = dict(
                **copy.deepcopy(record), reviewed_plan=accepted, tracking=checked_tracking, alignment=checked_alignment, reviewed_at=utc_now(),
                editor_fingerprint=edited_fingerprint, status='Human-reviewed AI draft; not a security certification')
            st.success('Review recorded for this session. Your downloads are ready below.')
        except ValidationError as exc:
            st.error(str(exc))
    reviewed = st.session_state.get('reviewed')
    if reviewed and confirmed and reviewed['editor_fingerprint'] == edited_fingerprint:
        st.subheader('3 · CISO sign-off (optional)')
        st.caption(NOTICE)
        with st.form('signoff_form'):
            name = st.text_input('Reviewer name or alias', max_chars=100, key='sign_name')
            role = st.text_input('Reviewer role', value='CISO', max_chars=100, key='sign_role')
            decision = st.selectbox('Decision', DECISIONS, key='sign_decision')
            rationale = st.text_area('Decision rationale and conditions', max_chars=1800, key='sign_rationale')
            attested = st.checkbox('I am authorized to record this decision and have reviewed the complete plan, assignments and standards mappings.', key='sign_attested')
            if st.form_submit_button('Record CISO decision'):
                try:
                    reviewed['signoff'] = create_signoff(reviewed, name, role, decision, rationale, attested)
                except ValidationError as exc:
                    st.error(str(exc))
        signoff = current_signoff(reviewed)
        if signoff:
            st.info(f"Recorded decision: {signoff['decision']} · {signoff['name']} · {signoff['signed_at']}")
            st.caption('Any change to inputs, actions, tracking, alignment or review invalidates this decision. Downloads are editable records, not tamper-proof evidence.')
            if st.button('Withdraw recorded decision'):
                reviewed.pop('signoff', None)
                st.rerun()
        else:
            st.info('Not signed off. You may export the reviewed plan without a CISO decision.')
        st.subheader('4 · Export your reviewed plan')
        st.caption('CSV includes all actions and assignments. JSON includes the input, original AI draft and reviewed version. Store downloads securely.')
        x, y, z = st.columns(3)
        x.download_button('Download action plan · CSV', export_csv(reviewed), 'ciso-reviewed-actions.csv', 'text/csv', width='stretch')
        y.download_button('Download full record · JSON', json.dumps(reviewed, indent=2, ensure_ascii=False), 'ciso-reviewed-record.json', 'application/json', width='stretch')
        z.download_button('Download action plan · Word', export_docx(reviewed), 'ciso-reviewed-action-plan.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', width='stretch')
    elif reviewed:
        st.info('The review or action assignments changed. Confirm again to refresh your export.')


st.markdown('''<style>
.block-container {max-width:1120px;padding-top:2.2rem;}
h1 {letter-spacing:-.045em;}
div[data-testid="stMetric"] {background:#eef4fb;padding:16px;border-radius:12px;}
div[data-testid="stMetric"] label, div[data-testid="stMetric"] div {color:#173459;}
</style>''', unsafe_allow_html=True)

with st.sidebar:
    brand_logo(280)
    st.caption('REMEDIATION PLANNER · V4')
    st.markdown('**1 · Describe**\n\nEnter or import findings.\n\n**2 · Review**\n\nEdit and assign actions.\n\n**3 · Sign off**\n\nRecord a CISO decision.\n\n**4 · Export**\n\nDownload your reviewed plan.')
    st.divider()
    st.markdown('**Save and resume**')
    session_download = st.empty()
    st.file_uploader('Restore session or full record', type=['json'], key='session_upload', on_change=capture_upload, args=('session_upload', 'session_bytes'), help='Maximum 500 KB. Restore replaces the current work after validation.')
    st.button('Restore uploaded session', on_click=restore_session, width='stretch')
    st.caption('Restoring replaces your current work. Download it first if you want to keep it. Imported plans require a new review.')
    st.divider()
    st.button('Clear session data', on_click=clear_session, width='stretch')
    st.caption('No database or automatic saving. Downloads remain on your device; clearing cannot remove provider records.')

brand_logo(430)
st.caption('CISO.ai / SMB security operations')
st.title('Turn findings into next steps.')
st.write('Create a practical remediation draft, review the reasoning, and track the actions you choose.')
st.info('Use sanitized, authorized findings only. This app does not scan devices, apply fixes, or certify security.')
if 'import_notice' in st.session_state:
    level, message = st.session_state.pop('import_notice')
    getattr(st, level)(message)
api_key = setting('GEMINI_API_KEY').strip()
model = setting('GEMINI_MODEL', 'gemini-3.1-flash-lite').strip()
configured = bool(api_key and api_key != 'PASTE_YOUR_KEY_HERE')
st.caption(f'AI model: {model}')
if not configured:
    st.warning('Gemini is not configured. Add GEMINI_API_KEY to .streamlit/secrets.toml locally, or to Settings → Secrets in Streamlit Cloud, then restart. Do not put the key in GitHub.')
with st.expander('Data use and Gemini setup'):
    st.write('Replace real company names, hostnames and people with aliases. Never enter credentials, personal data, customer records or confidential evidence.')
    st.write('Only the business context, constraints and findings are sent to Google Gemini when you generate a draft. Owners, dates, action statuses, standards mappings and sign-off details stay in the app session and your downloads.')
    st.write('The app does not intentionally save inputs or plans to disk or a database. Hosting and provider policies still apply. Google’s free tier may use inputs and outputs to improve its products.')
    st.write('For model-not-found errors, set GEMINI_MODEL to the exact text-model identifier available to your AI Studio project. For quota errors, check AI Studio usage and wait for the quota to reset. The app never upgrades billing or switches models automatically.')
    st.link_button('Open Google AI Studio', 'https://aistudio.google.com/apikey')
    st.write('Validate AI recommendations before acting. Session files are editable JSON, not signed evidence or proof of prior approval.')

st.subheader('1 · Describe your situation')
with st.expander('Import findings from CSV'):
    st.download_button('Download blank CSV template', csv_template(), 'ciso-findings-template.csv', 'text/csv')
    st.caption('UTF-8 CSV, up to five findings and 500 KB. Import replaces the findings and clears any existing plan; business context stays. Download your current session first if needed.')
    st.write('Required headers: asset, observation, severity, exposure, criticality. Use aliases. Severity: Unknown/Critical/High/Medium/Low. Exposure: Unknown/Internet-facing/Internal/Isolated. Criticality: Unknown/High/Medium/Low.')
    st.file_uploader('Choose findings CSV', type=['csv'], key='csv_upload', on_change=capture_upload, args=('csv_upload', 'csv_bytes'))
    st.button('Import CSV findings', on_click=import_findings)
context = st.text_area('Business context', max_chars=1000, key='context', placeholder='Describe the service, why it matters, and the impact of an outage. Use aliases.')
constraints = st.text_area('Operational constraints (optional)', max_chars=800, key='constraints', placeholder='Maintenance windows, team capacity, dependencies, or change restrictions.')
st.session_state.setdefault('count', 1)
count = st.number_input('Number of findings', min_value=1, max_value=5, value=None, step=1, key='count')
if count is None:
    st.info('Enter a finding count. One finding is shown while the count is blank.')
    count = 1
rows = []
for i in range(int(count)):
    with st.expander(f'Finding F{i+1}', expanded=True):
        asset = st.text_input('Asset alias', max_chars=80, key=f'asset_{i}', placeholder='Use a non-identifying asset label')
        observation = st.text_area('Observed issue and supporting facts', max_chars=1200, key=f'observation_{i}', placeholder='Describe what you observed, how it was checked, and any uncertainty.')
        a, b, c = st.columns(3)
        severity = a.selectbox('Reported severity', SEVERITIES, key=f'severity_{i}')
        exposure = b.selectbox('Exposure', EXPOSURES, key=f'exposure_{i}')
        criticality = c.selectbox('Business criticality', CRITICALITIES, key=f'criticality_{i}')
        rows.append(dict(asset=asset, observation=observation, severity=severity, exposure=exposure, criticality=criticality))
raw_input = dict(business_context=context, constraints=constraints, findings=rows)
payload, input_error = None, None
try:
    payload = validate_input(raw_input)
except ValidationError as exc:
    input_error = str(exc)
flags = privacy_flags(raw_input)
if flags:
    st.warning('Remove detected sensitive details before generating: ' + ', '.join(flags) + '. Detection is incomplete; review every field yourself.')
consent = st.checkbox('I am authorized to use these sanitized findings and agree to send the entered information to Google Gemini.', key='consent')
if st.button('Generate remediation draft', type='primary', disabled=not configured, width='stretch'):
    if input_error:
        st.error(input_error)
    elif flags:
        st.error('Remove the detected sensitive details before sending.')
    elif not consent:
        st.error('Confirm authorization and data sharing before generating.')
    elif time.time() - st.session_state.get('last_call', 0) < 30:
        st.error('Please wait 30 seconds between generation requests.')
    else:
        reset_plan()
        st.session_state['last_call'] = time.time()
        try:
            try:
                limit = max(1, min(int(setting('MAX_CALLS_PER_DAY', '100')), 1000))
            except ValueError:
                limit = 100
            budget().reserve(limit)
            with st.spinner('Preparing your remediation draft…'):
                plan = generate_plan(payload, api_key, model)
            st.session_state['record'] = dict(input=payload, input_fingerprint=fingerprint(payload), original_ai_plan=plan,
                model=model, generated_at=utc_now(), provenance='AI-generated draft, requiring human review')
        except AIError as exc:
            st.error(str(exc))
record = st.session_state.get('record')
if record:
    if payload is None or fingerprint(payload) != record['input_fingerprint']:
        if st.session_state.get('reviewed'):
            st.session_state['reviewed'].pop('signoff', None)
        st.warning('Your inputs changed. Generate a new draft before reviewing or exporting. Your previous edits remain available in a session download.')
    else:
        review_plan(record)
try:
    session = make_session(raw_input, record, st.session_state.get('editor_cache', record['original_ai_plan'] if record else None), st.session_state.get('tracking', default_tracking(record['original_ai_plan']) if record else {}), st.session_state.get('alignment'))
    session_bytes = json.dumps(session, indent=2, ensure_ascii=False)
    parse_session(session_bytes.encode())  # Only offer reloadable snapshots.
    session_download.download_button('Download session · JSON', session_bytes, 'ciso-session.json', 'application/json', width='stretch')
except ValidationError:
    session_download.info('Complete any empty action text before saving the session. Partially entered findings can still be saved.')
st.divider()
st.caption('CISO.ai · Findings → draft → human review → action tracking → export')
