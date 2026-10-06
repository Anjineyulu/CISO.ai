"""Headless Streamlit interaction checks; AI is mocked, never billed."""
from pathlib import Path
from datetime import date
import io
import json
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from test_core import plan_fixture
from ai_client import AIError
from session_io import make_session, csv_template

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


def app(configured=True):
    at = AppTest.from_file(APP, default_timeout=20)
    if configured:
        at.secrets['GEMINI_API_KEY'] = 'unit-test-not-a-key'
    return at.run()


def button(at, label):
    return next(b for b in at.button if b.label == label)


def complete_input(at):
    at.text_area(key='context').set_value('Synthetic context for automated software tests only.')
    at.text_input(key='asset_0').set_value('Test asset')
    at.text_area(key='observation_0').set_value('Synthetic observation for automated software tests only.')
    at.checkbox(key='consent').check()
    return at.run()


def generate(at):
    with patch('ai_client.generate_plan', return_value=plan_fixture()) as call:
        button(at, 'Generate remediation draft').click().run()
    return call


class UITests(unittest.TestCase):
    def test_tracking_filters_and_export_invalidation(self):
        at = complete_input(app())
        generate(at)
        at.text_input(key='track_F1_owner').set_value('IT lead')
        at.date_input(key='track_F1_date').set_value(date(2026, 11, 1))
        at.selectbox(key='track_F1_status').set_value('In progress').run()
        at.checkbox(key='confirmed').check().run()
        button(at, 'Confirm review and prepare export').click().run()
        self.assertEqual(at.session_state['reviewed']['tracking']['F1']['owner'], 'IT lead')
        at.multiselect(key='filter_status').set_value(['Completed']).run()
        self.assertTrue(any('No actions match' in i.value for i in at.info))
        self.assertEqual(len(at.get('download_button')), 5)
        self.assertEqual(len(at.session_state['reviewed']['reviewed_plan']['items']), 1)
        at.text_input(key='track_F1_owner').set_value('Backup lead').run()
        self.assertEqual(len(at.get('download_button')), 2)
        self.assertEqual(len(at.exception), 0)

    # AppTest does not expose the browser file-upload action. Seed its captured bytes.
    def test_session_upload_restores_work_and_requires_new_review(self):
        at = complete_input(app())
        generate(at)
        at.text_area(key='review_F1_action').set_value('Preserved human edit.')
        at.text_input(key='track_F1_owner').set_value('Test owner').run()
        workspace = make_session(at.session_state['record']['input'], at.session_state['record'],
                                 at.session_state['editor_cache'], at.session_state['tracking'])
        restored = app()
        restored.session_state['session_bytes'] = json.dumps(workspace).encode()
        with patch('ai_client.generate_plan') as call:
            button(restored, 'Restore uploaded session').click().run()
        call.assert_not_called()
        self.assertEqual(len(restored.exception), 0)
        self.assertEqual(restored.text_area(key='review_F1_action').value, 'Preserved human edit.')
        self.assertEqual(restored.text_input(key='track_F1_owner').value, 'Test owner')
        self.assertFalse(restored.checkbox(key='confirmed').value)
        self.assertEqual(len(restored.get('download_button')), 2)
        self.assertNotIn('reviewed', restored.session_state)

    def test_csv_upload_replaces_findings_and_invalid_import_keeps_work(self):
        at = complete_input(app())
        generate(at)
        at.session_state['csv_bytes'] = b'bad,header\n'
        button(at, 'Import CSV findings').click().run()
        self.assertIn('record', at.session_state)
        self.assertTrue(at.error)
        at.session_state['csv_bytes'] = (csv_template() + 'Imported alias,Synthetic imported test observation,High,Internal,Medium\n').encode()
        with patch('ai_client.generate_plan') as call:
            button(at, 'Import CSV findings').click().run()
        call.assert_not_called()
        self.assertEqual(at.text_input(key='asset_0').value, 'Imported alias')
        self.assertEqual(at.selectbox(key='severity_0').value, 'High')
        self.assertNotIn('record', at.session_state)
        self.assertFalse(at.checkbox(key='consent').value)
        self.assertEqual(len(at.exception), 0)

    def test_invalid_session_keeps_current_work(self):
        at = complete_input(app())
        generate(at)
        at.session_state['session_bytes'] = b'{"version":999}'
        button(at, 'Restore uploaded session').click().run()
        self.assertIn('record', at.session_state)
        self.assertTrue(at.error)
        self.assertEqual(len(at.exception), 0)

    def test_missing_key_and_initial_load(self):
        at = app(False)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(button(at, 'Generate remediation draft').disabled)
        self.assertEqual(len(at.get('download_button')), 2)

    def test_validation_blocks_network(self):
        at = app()
        with patch('ai_client.generate_plan') as call:
            button(at, 'Generate remediation draft').click().run()
        call.assert_not_called()
        self.assertTrue(at.error)

    def test_consent_and_privacy_block_network(self):
        at = complete_input(app())
        at.checkbox(key='consent').uncheck().run()
        with patch('ai_client.generate_plan') as call:
            button(at, 'Generate remediation draft').click().run()
        call.assert_not_called()
        at.checkbox(key='consent').check()
        at.text_input(key='asset_0').set_value('test@example.org').run()
        with patch('ai_client.generate_plan') as call:
            button(at, 'Generate remediation draft').click().run()
        call.assert_not_called()

    def test_generate_review_edit_export_and_stale_inputs(self):
        at = complete_input(app())
        call = generate(at)
        call.assert_called_once()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.get('download_button')), 2)
        at.checkbox(key='confirmed').check().run()
        button(at, 'Confirm review and prepare export').click().run()
        self.assertEqual(len(at.get('download_button')), 5)
        at.text_area(key='review_F1_action').set_value('Human changed this test action.').run()
        self.assertEqual(len(at.get('download_button')), 2)
        button(at, 'Confirm review and prepare export').click().run()
        self.assertEqual(len(at.get('download_button')), 5)
        self.assertEqual(at.session_state['reviewed']['reviewed_plan']['items'][0]['action'], 'Human changed this test action.')
        self.assertEqual(at.session_state['reviewed']['original_ai_plan'], plan_fixture())
        at.text_area(key='context').set_value('Different business context for this test.').run()
        self.assertEqual(len(at.get('download_button')), 2)
        self.assertTrue(any('inputs changed' in w.value for w in at.warning))

    def test_sessions_are_isolated_and_clear_works(self):
        first = complete_input(app())
        generate(first)
        second = app()
        self.assertNotIn('record', second.session_state)
        self.assertEqual(second.text_area(key='context').value, '')
        button(first, 'Clear session data').click().run()
        self.assertEqual(first.text_area(key='context').value, '')
        self.assertNotIn('record', first.session_state)
        self.assertEqual(len(first.exception), 0)

    def test_api_failure_and_retry_clear_old_result(self):
        at = complete_input(app())
        generate(at)
        at.session_state['last_call'] = 0
        with patch('ai_client.generate_plan', side_effect=AIError('Test API failure.')):
            button(at, 'Generate remediation draft').click().run()
        self.assertNotIn('record', at.session_state)
        self.assertTrue(any('Test API failure' in e.value for e in at.error))
        self.assertEqual(len(at.exception), 0)


if __name__ == '__main__':
    unittest.main()
