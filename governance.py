"""Human-entered standards references and self-declared, session-only decisions."""
from datetime import datetime, timezone
from core import ValidationError, clean_text, fingerprint

NIST_SOURCE = 'https://www.nist.gov/cyberframework'
CIS_SOURCE = 'https://www.cisecurity.org/controls/v8-1'
NIST = dict(line.split('|', 1) for line in '''GV.OC|Organizational Context
GV.RM|Risk Management Strategy
GV.RR|Roles, Responsibilities, and Authorities
GV.PO|Policy
GV.OV|Oversight
GV.SC|Cybersecurity Supply Chain Risk Management
ID.AM|Asset Management
ID.RA|Risk Assessment
ID.IM|Improvement
PR.AA|Identity Management, Authentication, and Access Control
PR.AT|Awareness and Training
PR.DS|Data Security
PR.PS|Platform Security
PR.IR|Technology Infrastructure Resilience
DE.CM|Continuous Monitoring
DE.AE|Adverse Event Analysis
RS.MA|Incident Management
RS.AN|Incident Analysis
RS.CO|Incident Response Reporting and Communication
RS.MI|Incident Mitigation
RC.RP|Incident Recovery Plan Execution
RC.CO|Incident Recovery Communication'''.splitlines())
# Deliberately limited control-level catalog, not a safeguard-level crosswalk.
CIS = {'3': 'Data Protection', '6': 'Access Control Management',
       '8': 'Audit Log Management', '11': 'Data Recovery', '17': 'Incident Response Management'}
CATALOG = {**{f'NIST CSF 2.0 {k}': v for k, v in NIST.items()},
           **{f'CIS Controls v8.1 {k}': v for k, v in CIS.items()}}
ASSESSMENTS = ['Not assessed', 'Gap identified', 'Action planned', 'Evidence reviewed']
DECISIONS = ['Approve plan', 'Changes requested']
NOTICE = 'Self-declared decision; identity is not verified. This is not a digital signature, compliance certification, or proof of remediation.'
ALIGNMENT_NOTICE = 'User-selected advisory references only. NIST mappings are category-level; CIS mappings cover five selected controls, not individual safeguards. No compliance or coverage score is calculated.'


def default_alignment(plan):
    return {r['finding_id']: dict(references=[], assessment='Not assessed', rationale='', evidence='') for r in plan['items']}


def validate_alignment(raw, plan, final=False):
    if not isinstance(raw, dict) or set(raw) != set(default_alignment(plan)):
        raise ValidationError('Standards alignment must match every finding.')
    out = {}
    for fid, row in raw.items():
        if not isinstance(row, dict) or set(row) != {'references', 'assessment', 'rationale', 'evidence'}:
            raise ValidationError('Invalid standards-alignment fields.')
        refs = row['references']
        if not isinstance(refs, list) or any(not isinstance(r, str) or r not in CATALOG for r in refs) or len(refs) != len(set(refs)):
            raise ValidationError('Choose references from the supported catalog.')
        if row['assessment'] not in ASSESSMENTS:
            raise ValidationError('Invalid alignment assessment.')
        rationale = clean_text(row['rationale'], 'Mapping rationale', 1800, 0)
        evidence = clean_text(row['evidence'], 'Evidence reference', 1000, 0)
        if final and refs and not rationale:
            raise ValidationError(f'{fid}: explain why the selected references apply.')
        if final and row['assessment'] != 'Not assessed' and not refs:
            raise ValidationError(f'{fid}: select a reference before recording an assessment.')
        if final and row['assessment'] == 'Evidence reviewed' and not evidence:
            raise ValidationError(f'{fid}: add a sanitized evidence reference for evidence reviewed.')
        out[fid] = dict(references=sorted(refs), assessment=row['assessment'], rationale=rationale, evidence=evidence)
    return out


def record_digest(record):
    return fingerprint({k: record.get(k) for k in ('input', 'original_ai_plan', 'reviewed_plan', 'tracking', 'alignment', 'model', 'generated_at', 'reviewed_at')})


def create_signoff(record, name, role, decision, rationale, attested):
    if not attested:
        raise ValidationError('Confirm your authority and review before recording a decision.')
    if decision not in DECISIONS:
        raise ValidationError('Invalid sign-off decision.')
    return dict(name=clean_text(name, 'Reviewer name or alias', 100),
                role=clean_text(role, 'Reviewer role', 100), decision=decision,
                rationale=clean_text(rationale, 'Decision rationale', 1800),
                signed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                record_digest=record_digest(record), notice=NOTICE)


def current_signoff(record):
    signoff = record.get('signoff')
    return signoff if isinstance(signoff, dict) and signoff.get('record_digest') == record_digest(record) else None


def governance_columns(record, fid):
    a = record.get('alignment', {}).get(fid, default_alignment(record['reviewed_plan'])[fid])
    s = current_signoff(record) or {}
    return dict(standards_references='; '.join(a['references']), alignment_assessment=a['assessment'],
                alignment_rationale=a['rationale'], evidence_reference=a['evidence'],
                signoff_decision=s.get('decision', 'Not signed off'), signoff_reviewer=s.get('name', ''),
                signoff_role=s.get('role', ''), signoff_rationale=s.get('rationale', ''),
                signoff_at=s.get('signed_at', ''), signoff_record_digest=s.get('record_digest', ''),
                signoff_notice=NOTICE)
