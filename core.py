"""Validation and exports. No network, persistence, or Streamlit dependency."""
import csv
import hashlib
import io
import json
import re

PRIORITIES = ['Urgent', 'High', 'Medium', 'Low', 'Needs validation']
SEVERITIES = ['Unknown', 'Critical', 'High', 'Medium', 'Low']
EXPOSURES = ['Unknown', 'Internet-facing', 'Internal', 'Isolated']
CRITICALITIES = ['Unknown', 'High', 'Medium', 'Low']
FIELDS = ['finding_id', 'priority', 'rationale', 'action', 'verification', 'uncertainty']


class ValidationError(ValueError):
    pass


def clean_text(value, label, limit, minimum=1):
    if not isinstance(value, str):
        raise ValidationError(f'{label} must be text.')
    value = value.strip()
    if not minimum <= len(value) <= limit:
        raise ValidationError(f'{label} needs {minimum}–{limit} characters.')
    return value


def validate_input(raw):
    if not isinstance(raw, dict):
        raise ValidationError('Input must be a record.')
    context = clean_text(raw.get('business_context'), 'Business context', 1000, 10)
    constraints = clean_text(raw.get('constraints', ''), 'Constraints', 800, 0)
    rows = raw.get('findings')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValidationError('Enter between one and five findings.')
    findings = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValidationError('Each finding must be a record.')
        out = {'finding_id': f'F{i}'}
        for field, limit, minimum in [('asset', 80, 1), ('observation', 1200, 10)]:
            out[field] = clean_text(row.get(field), f'Finding {i}: {field}', limit, minimum)
        for field, allowed in [('severity', SEVERITIES), ('exposure', EXPOSURES), ('criticality', CRITICALITIES)]:
            if row.get(field) not in allowed:
                raise ValidationError(f'Finding {i}: invalid {field}.')
            out[field] = row[field]
        findings.append(out)
    return {'business_context': context, 'constraints': constraints, 'findings': findings}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def privacy_flags(payload):
    """Best-effort reminders only; not a complete redaction or DLP engine."""
    text = json.dumps(payload)
    patterns = {
        'email address': r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',
        'IP address': r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        'possible credential': r'(?i)(?:password|api[_ -]?key|secret|token)\s*[:=]\s*\S+|-----BEGIN .*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{12,}',
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]


def validate_plan(plan, payload):
    if not isinstance(plan, dict) or set(plan) != {'items'} or not isinstance(plan['items'], list):
        raise ValidationError('The model returned an invalid plan. No result was accepted.')
    expected = {row['finding_id'] for row in payload['findings']}
    items = plan['items']
    if len(items) != len(expected):
        raise ValidationError('The plan must address every submitted finding exactly once.')
    seen = set()
    clean = []
    for row in items:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValidationError('A plan item has missing or unexpected fields.')
        fid = row['finding_id']
        if not isinstance(fid, str) or fid not in expected or fid in seen:
            raise ValidationError('The plan contains an unknown or repeated finding reference.')
        seen.add(fid)
        if row['priority'] not in PRIORITIES:
            raise ValidationError('The plan contains an invalid priority.')
        out = {'finding_id': fid, 'priority': row['priority']}
        for field in FIELDS[2:]:
            out[field] = clean_text(row[field], field.capitalize(), 1800)
        clean.append(out)
    return {'items': sorted(clean, key=lambda row: (PRIORITIES.index(row['priority']), row['finding_id']))}


def csv_cell(value):
    # Protect CSV consumers against spreadsheet formula injection, including whitespace prefixes.
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def export_csv(record):
    stream = io.StringIO(newline='')
    fields = FIELDS + ['owner', 'target_date', 'action_status', 'review_status', 'model', 'generated_at', 'reviewed_at']
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in record['reviewed_plan']['items']:
        tracking = record.get('tracking', {}).get(row['finding_id'], {})
        values = dict(row, owner=tracking.get('owner', ''), target_date=tracking.get('target_date', ''),
                      action_status=tracking.get('status', 'Not started'),
                      review_status='Human-reviewed AI draft; not a security certification',
                      model=record['model'], generated_at=record['generated_at'], reviewed_at=record['reviewed_at'])
        writer.writerow({key: csv_cell(value) for key, value in values.items()})
    return '\ufeff' + stream.getvalue()
