"""Synthetic behavior tests, not compliance evaluation."""
import copy, csv, io, json, unittest
from docx import Document
from core import ValidationError, export_csv
from governance import default_alignment, validate_alignment, create_signoff, current_signoff
from session_io import default_tracking, make_session, parse_session
from word_export import export_docx
from test_session_io import record_fixture
from test_core import plan_fixture
from test_ui import app, complete_input, generate, button


def reviewed():
    p = plan_fixture()
    r = record_fixture() | dict(reviewed_plan=p, tracking=default_tracking(p), alignment=default_alignment(p), reviewed_at='2026-10-06T00:00:00Z')
    r['alignment']['F1'] = dict(references=['NIST CSF 2.0 PR.AA', 'CIS Controls v8.1 6'], assessment='Action planned', rationale='Synthetic mapping rationale.', evidence='Test evidence ID')
    return r


class GovernanceTests(unittest.TestCase):
    def test_mapping_requirements(self):
        r = reviewed()
        validate_alignment(r['alignment'], r['reviewed_plan'], final=True)
        for change in [dict(references=['made up']), dict(rationale=''), dict(assessment='Evidence reviewed', evidence=''), dict(assessment='Compliant'), dict(references=[])]:
            a = copy.deepcopy(r['alignment']); a['F1'].update(change)
            with self.assertRaises(ValidationError):
                validate_alignment(a, r['reviewed_plan'], final=True)

    def test_required_signoff_fields_and_digest(self):
        r = reviewed()
        for args in [('', 'CISO', 'Approve plan', 'Test rationale', True), ('Reviewer', '', 'Approve plan', 'Test rationale', True), ('Reviewer', 'CISO', 'Approve plan', '', True), ('Reviewer', 'CISO', 'Approve plan', 'Test rationale', False)]:
            with self.assertRaises(ValidationError): create_signoff(r, *args)
        r['signoff'] = create_signoff(r, 'Reviewer', 'CISO', 'Changes requested', 'Test rationale', True)
        self.assertIsNotNone(current_signoff(r))
        for field in ['input', 'reviewed_plan', 'tracking', 'alignment', 'reviewed_at']:
            changed = copy.deepcopy(r); changed[field] = None
            self.assertIsNone(current_signoff(changed))

    def test_exports_and_import_discard_decision(self):
        r = reviewed()
        r['signoff'] = create_signoff(r, '=Test reviewer', 'CISO', 'Changes requested', 'Synthetic decision rationale.', True)
        row = next(csv.DictReader(io.StringIO(export_csv(r).lstrip('\ufeff'))))
        self.assertEqual(row['signoff_decision'], 'Changes requested')
        self.assertEqual(row['signoff_reviewer'], "'=Test reviewer")
        self.assertIn('PR.AA', row['standards_references'])
        doc = Document(io.BytesIO(export_docx(r)))
        text = '\n'.join(p.text for p in doc.paragraphs)
        for value in ['Changes requested', 'Synthetic decision rationale.', 'NIST CSF 2.0 PR.AA', r['signoff']['record_digest']]: self.assertIn(value, text)
        restored = parse_session(json.dumps(r).encode())
        self.assertEqual(restored['alignment']['F1']['assessment'], 'Action planned')
        self.assertNotIn('signoff', restored['record'])
        old = make_session(r['input'], record_fixture(), r['reviewed_plan'], r['tracking'])
        old['version'] = 1; del old['alignment']
        self.assertEqual(parse_session(json.dumps(old).encode())['alignment'], default_alignment(r['reviewed_plan']))

    def test_ui_mapping_signoff_invalidation_and_restore(self):
        at = complete_input(app()); generate(at)
        at.multiselect(key='align_F1_refs').set_value(['NIST CSF 2.0 PR.AA']).run()
        at.checkbox(key='confirmed').check().run()
        button(at, 'Confirm review and prepare export').click().run()
        self.assertTrue(at.error)
        at.text_area(key='align_F1_reason').set_value('Synthetic mapping reason.').run()
        button(at, 'Confirm review and prepare export').click().run()
        at.text_input(key='sign_name').set_value('Test reviewer')
        at.text_area(key='sign_rationale').set_value('Synthetic approval explanation.')
        at.checkbox(key='sign_attested').check()
        button(at, 'Record CISO decision').click().run()
        self.assertIsNotNone(current_signoff(at.session_state['reviewed']))
        at.multiselect(key='filter_status').set_value(['Completed']).run()
        self.assertIsNotNone(current_signoff(at.session_state['reviewed']))
        saved = json.dumps(at.session_state['reviewed']).encode()
        at.text_area(key='align_F1_reason').set_value('Changed mapping reason.').run()
        self.assertNotIn('signoff', at.session_state['reviewed'])
        at.text_area(key='align_F1_reason').set_value('Synthetic mapping reason.').run()
        self.assertNotIn('signoff', at.session_state['reviewed'])
        at.session_state['session_bytes'] = saved
        button(at, 'Restore uploaded session').click().run()
        self.assertFalse(at.checkbox(key='confirmed').value)
        self.assertNotIn('reviewed', at.session_state)
        self.assertEqual(at.multiselect(key='align_F1_refs').value, ['NIST CSF 2.0 PR.AA'])
        self.assertFalse(at.exception)

    def test_input_change_permanently_invalidates_signoff(self):
        at = complete_input(app()); generate(at)
        at.checkbox(key='confirmed').check().run()
        button(at, 'Confirm review and prepare export').click().run()
        at.text_input(key='sign_name').set_value('Reviewer')
        at.text_area(key='sign_rationale').set_value('Synthetic approval rationale.')
        at.checkbox(key='sign_attested').check()
        button(at, 'Record CISO decision').click().run()
        self.assertIn('signoff', at.session_state['reviewed'])
        before = at.text_area(key='context').value
        at.text_area(key='context').set_value('Changed synthetic business context.').run()
        self.assertNotIn('signoff', at.session_state['reviewed'])
        at.text_area(key='context').set_value(before).run()
        self.assertIsNone(current_signoff(at.session_state['reviewed']))
        self.assertFalse(at.exception)
