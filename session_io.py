"""Bounded plain CSV/JSON import; no deserialization of executable objects."""
import csv
import io
import json
from datetime import date, datetime, timezone
from core import (CRITICALITIES, EXPOSURES, SEVERITIES, ValidationError, clean_text,
                  fingerprint, validate_input, validate_plan)

from governance import default_alignment, validate_alignment

CSV_FIELDS = ['asset', 'observation', 'severity', 'exposure', 'criticality']
STATUSES = ['Not started', 'In progress', 'Blocked', 'Completed']
MAX_FILE_BYTES = 500_000


def csv_template():
    return ','.join(CSV_FIELDS) + '\r\n'


def decode_file(data):
    if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
        raise ValidationError('Upload a file smaller than 500 KB.')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValidationError('Save the file as UTF-8 and try again.') from None


def parse_csv(data):
    try:
        reader = csv.DictReader(io.StringIO(decode_file(data), newline=''), strict=True)
        if reader.fieldnames != CSV_FIELDS:
            raise ValidationError('CSV headers must match the blank template, in the same order.')
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValidationError('Each CSV row must have exactly five columns. Quote text containing commas.')
            if not any(value.strip() for value in row.values()):
                continue
            rows.append({key: value.strip() for key, value in row.items()})
            if len(rows) > 5:
                raise ValidationError('The MVP accepts at most five findings per file.')
    except csv.Error:
        raise ValidationError('The CSV format is invalid. Use the provided template.') from None
    # Reuse input validation with temporary context; this context is never saved or sent.
    return validate_input({'business_context': 'CSV validation only', 'constraints': '', 'findings': rows})['findings']


def validate_draft(raw):
    if not isinstance(raw, dict) or set(raw) != {'business_context', 'constraints', 'findings'}:
        raise ValidationError('The session has invalid input fields.')
    out = {'business_context': clean_text(raw['business_context'], 'Business context', 1000, 0),
           'constraints': clean_text(raw['constraints'], 'Constraints', 800, 0)}
    rows = raw['findings']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValidationError('The session must contain one to five findings.')
    out['findings'] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) not in (set(CSV_FIELDS), set(CSV_FIELDS) | {'finding_id'}):
            raise ValidationError('A saved finding has invalid fields.')
        clean = {'asset': clean_text(row['asset'], 'Asset', 80, 0),
                 'observation': clean_text(row['observation'], 'Observation', 1200, 0)}
        for key, options in [('severity', SEVERITIES), ('exposure', EXPOSURES), ('criticality', CRITICALITIES)]:
            if row[key] not in options:
                raise ValidationError(f'Invalid saved {key}.')
            clean[key] = row[key]
        out['findings'].append(clean)
    return out


def default_tracking(plan):
    return {row['finding_id']: {'owner': '', 'target_date': '', 'status': 'Not started'} for row in plan['items']}


def validate_tracking(raw, plan):
    expected = {row['finding_id'] for row in plan['items']}
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValidationError('Action tracking must match all finding references.')
    result = {}
    for fid, row in raw.items():
        if not isinstance(row, dict) or set(row) != {'owner', 'target_date', 'status'}:
            raise ValidationError('Invalid action-tracking fields.')
        owner = clean_text(row['owner'], 'Owner alias', 80, 0)
        target = clean_text(row['target_date'], 'Target date', 10, 0)
        if target:
            try:
                parsed = date.fromisoformat(target)
                if parsed.isoformat() != target or not 1900 <= parsed.year <= 2100:
                    raise ValueError()
            except ValueError:
                raise ValidationError('Target dates must be YYYY-MM-DD, between 1900 and 2100.') from None
        if row['status'] not in STATUSES:
            raise ValidationError('Invalid action status.')
        result[fid] = dict(owner=owner, target_date=target, status=row['status'])
    return result


def timestamp(value):
    value = clean_text(value, 'Saved timestamp', 50)
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValidationError('The saved timestamp is invalid.') from None
    return value


def validate_record(record):
    if not isinstance(record, dict):
        raise ValidationError('The saved AI record is invalid.')
    payload = validate_input(record.get('input'))
    original = validate_plan(record.get('original_ai_plan'), payload)
    return dict(input=payload, input_fingerprint=fingerprint(payload), original_ai_plan=original,
                model=clean_text(record.get('model'), 'Model name', 100),
                generated_at=timestamp(record.get('generated_at')),
                provenance='Imported draft: origin and prior review are not independently verified')


def make_session(raw, record=None, editor_plan=None, tracking=None, alignment=None):
    return {'format': 'ciso.ai-session', 'version': 2,
            'saved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'input': validate_draft(raw), 'record': record,
            'editor_plan': editor_plan, 'tracking': tracking or {},
            'alignment': alignment if alignment is not None else (default_alignment(editor_plan) if editor_plan else {})}


def parse_session(data):
    try:
        obj = json.loads(decode_file(data))
    except (ValueError, RecursionError):
        raise ValidationError('The file is not a valid JSON session.') from None
    if not isinstance(obj, dict):
        raise ValidationError('The JSON must contain a CISO.ai session or full record.')
    if 'format' not in obj and {'input', 'original_ai_plan', 'reviewed_plan'} <= set(obj):
        # Also accept full-record exports from the earlier edition, as unverified drafts.
        old_record = validate_record(obj)
        old_plan = validate_plan(obj['reviewed_plan'], old_record['input'])
        obj = make_session(old_record['input'], old_record, old_plan, obj.get('tracking', default_tracking(old_plan)), obj.get('alignment', default_alignment(old_plan)))
    if obj.get('version') == 1 and type(obj.get('version')) is int and 'alignment' not in obj:
        obj['alignment'] = default_alignment(obj['editor_plan']) if isinstance(obj.get('editor_plan'), dict) and isinstance(obj['editor_plan'].get('items'), list) else {}
        obj['version'] = 2
    required = {'alignment', 'format', 'version', 'saved_at', 'input', 'record', 'editor_plan', 'tracking'}
    if set(obj) != required or obj['format'] != 'ciso.ai-session' or type(obj['version']) is not int or obj['version'] != 2:
        raise ValidationError('Unsupported session format or version. Use a CISO.ai session download.')
    result = make_session(validate_draft(obj['input']))
    result['saved_at'] = timestamp(obj['saved_at'])
    if obj['record'] is None:
        if obj['editor_plan'] is not None or obj['tracking'] != {} or obj['alignment'] != {}:
            raise ValidationError('A session without an AI draft cannot contain reviewed actions.')
        return result
    record = validate_record(obj['record'])
    editor = validate_plan(obj['editor_plan'], record['input'])
    tracking = validate_tracking(obj['tracking'], editor)
    result.update(record=record, editor_plan=editor, tracking=tracking, alignment=validate_alignment(obj['alignment'], editor))
    return result


def action_rows(plan, tracking, source, priorities=None, statuses=None):
    assets = {row['finding_id']: row['asset'] for row in source['findings']}
    return [{'Finding': row['finding_id'], 'Asset': assets[row['finding_id']],
             'Priority': row['priority'], 'Owner': tracking[row['finding_id']]['owner'],
             'Target date': tracking[row['finding_id']]['target_date'],
             'Status': tracking[row['finding_id']]['status'], 'Action': row['action']}
            for row in plan['items']
            if (not priorities or row['priority'] in priorities)
            and (not statuses or tracking[row['finding_id']]['status'] in statuses)]
