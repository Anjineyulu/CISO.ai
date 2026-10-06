"""Synthetic software fixtures only; these are not research or evaluation results."""
import copy
import csv
import io
import json
import unittest
from core import ValidationError, export_csv, fingerprint, validate_input
from session_io import (action_rows, csv_template, default_tracking, make_session,
                        parse_csv, parse_session, validate_tracking)
from test_core import input_fixture, plan_fixture


def record_fixture():
    payload = validate_input(input_fixture())
    return dict(input=payload, input_fingerprint=fingerprint(payload), original_ai_plan=plan_fixture(),
                model='gemini-test', generated_at='2026-10-04T10:00:00+00:00', provenance='Synthetic test')


def workspace_fixture():
    return make_session(input_fixture(), record_fixture(), plan_fixture(), default_tracking(plan_fixture()))


class SessionTests(unittest.TestCase):
    def test_csv_round_trip_with_bom_quotes_and_unicode(self):
        stream = io.StringIO(newline='')
        stream.write(csv_template())
        row = input_fixture()['findings'][0]
        row['observation'] = 'Synthetic, quoted observation\nwith a second line — test only.'
        csv.writer(stream).writerow(row[k] for k in ['asset','observation','severity','exposure','criticality'])
        parsed = parse_csv(('\ufeff' + stream.getvalue()).encode())
        self.assertEqual(parsed[0]['observation'], row['observation'])

    def test_csv_rejects_bad_headers_empty_invalid_enums_extra_rows_and_size(self):
        row = 'Asset,Synthetic observation for testing,Unknown,Unknown,Unknown\n'
        for content in [b'wrong,headers\n', csv_template().encode(), b'\xff', b'x'*500001,
                        (csv_template()+row*6).encode(),
                        (csv_template()+'A,Enough text for test,INVALID,Unknown,Unknown\n').encode(),
                        (csv_template()+row.strip()+',extra\n').encode()]:
            with self.subTest(content=content[:30]), self.assertRaises(ValidationError):
                parse_csv(content)

    def test_save_restore_preserves_edits_tracking_and_original(self):
        workspace = workspace_fixture()
        workspace['editor_plan']['items'][0]['action'] = 'Edited by test user.'
        workspace['tracking']['F1'] = dict(owner='IT lead', target_date='2026-11-01', status='In progress')
        restored = parse_session(json.dumps(workspace).encode())
        self.assertEqual(restored['editor_plan'], workspace['editor_plan'])
        self.assertEqual(restored['tracking'], workspace['tracking'])
        self.assertEqual(restored['record']['original_ai_plan'], plan_fixture())
        self.assertIn('Imported draft', restored['record']['provenance'])
        self.assertNotIn('confirmed', restored)

    def test_partial_input_can_be_saved(self):
        raw = input_fixture()
        raw['business_context'] = ''
        raw['findings'][0]['observation'] = ''
        restored = parse_session(json.dumps(make_session(raw)).encode())
        self.assertEqual(restored['input'], raw)

    def test_invalid_sessions_are_rejected(self):
        mutations = [lambda w: w.update(version=99), lambda w: w.update(version=True),
            lambda w: w.update(extra='not allowed'), lambda w: w.update(input=[]),
            lambda w: w['tracking']['F1'].update(status='Made up'),
            lambda w: w['tracking']['F1'].update(target_date='2026-02-30'),
            lambda w: w['editor_plan']['items'][0].update(finding_id='F99'),
            lambda w: w['record'].update(generated_at='bad-date')]
        for mutate in mutations:
            w = workspace_fixture()
            mutate(w)
            with self.assertRaises(ValidationError):
                parse_session(json.dumps(w).encode())
        for raw in [b'[]', b'not json', b'x'*500001]:
            with self.assertRaises(ValidationError):
                parse_session(raw)

    def test_legacy_full_record_can_be_restored(self):
        old = record_fixture() | {'reviewed_plan': plan_fixture(), 'reviewed_at': '2026-10-04T10:01:00Z'}
        restored = parse_session(json.dumps(old).encode())
        self.assertEqual(restored['tracking'], default_tracking(plan_fixture()))

    def test_stale_workspace_preserves_previous_plan(self):
        w = workspace_fixture()
        w['input']['business_context'] = 'A changed context for this test only.'
        restored = parse_session(json.dumps(w).encode())
        self.assertNotEqual(fingerprint(validate_input(restored['input'])), restored['record']['input_fingerprint'])

    def test_filter_does_not_modify_plan_or_tracking(self):
        w = workspace_fixture()
        before = copy.deepcopy(w)
        self.assertEqual(action_rows(w['editor_plan'], w['tracking'], w['record']['input'], ['High']), [])
        self.assertEqual(len(action_rows(w['editor_plan'], w['tracking'], w['record']['input'], statuses=['Not started'])), 1)
        self.assertEqual(w, before)

    def test_csv_contains_tracking_and_escapes_owner(self):
        record = record_fixture() | {'reviewed_plan': plan_fixture(), 'reviewed_at': 'test',
                                    'tracking': {'F1': dict(owner='=SUM(1,2)', target_date='2026-11-01', status='Blocked')}}
        rows = list(csv.DictReader(io.StringIO(export_csv(record).lstrip('\ufeff'))))
        self.assertEqual(rows[0]['owner'], "'=SUM(1,2)")
        self.assertEqual(rows[0]['action_status'], 'Blocked')
        self.assertEqual(rows[0]['target_date'], '2026-11-01')
