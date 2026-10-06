"""Synthetic fixtures for software tests only; not user-research or evaluation data."""
import copy
import io
import json
import unittest
import urllib.error
from ai_client import AIError, CallBudget, generate_plan
from core import ValidationError, export_csv, privacy_flags, validate_input, validate_plan


def input_fixture():
    return {'business_context': 'Synthetic service used only in automated software testing.',
            'constraints': 'Test maintenance window.',
            'findings': [{'asset': 'Test asset', 'observation': 'Synthetic observation for a software test only.',
                          'severity': 'Unknown', 'exposure': 'Unknown', 'criticality': 'Unknown'}]}


def plan_fixture():
    return {'items': [{'finding_id': 'F1', 'priority': 'Needs validation',
                      'rationale': 'Software test rationale.', 'action': 'Software test action.',
                      'verification': 'Software test verification.', 'uncertainty': 'Software test uncertainty.'}]}


class CoreTests(unittest.TestCase):
    def test_input_bounds_and_missing_fields(self):
        for change in [{'business_context': ''}, {'business_context': 'x'*1001}, {'findings': []}, {'findings': [input_fixture()['findings'][0]]*6}]:
            raw = input_fixture() | change
            with self.assertRaises(ValidationError):
                validate_input(raw)
        self.assertEqual(validate_input(input_fixture())['findings'][0]['finding_id'], 'F1')

    def test_invalid_enum(self):
        raw = input_fixture()
        raw['findings'][0]['exposure'] = 'invented'
        with self.assertRaises(ValidationError):
            validate_input(raw)

    def test_missing_extra_duplicate_and_unknown_references_rejected(self):
        payload = validate_input(input_fixture())
        for mutate in [lambda p: p['items'].clear(),
                       lambda p: p['items'].append(copy.deepcopy(p['items'][0])),
                       lambda p: p['items'][0].update(finding_id='F99'),
                       lambda p: p['items'][0].update(invented='extra'),
                       lambda p: p['items'][0].update(action=''),
                       lambda p: p['items'][0].update(priority='Very high')]:
            plan = plan_fixture()
            mutate(plan)
            with self.assertRaises(ValidationError):
                validate_plan(plan, payload)

    def test_two_findings_cannot_repeat_one_reference(self):
        raw = input_fixture()
        raw['findings'] *= 2
        plan = plan_fixture()
        plan['items'] *= 2
        with self.assertRaises(ValidationError):
            validate_plan(plan, validate_input(raw))

    def test_privacy_detection(self):
        self.assertEqual(privacy_flags(input_fixture()), [])
        self.assertIn('email address', privacy_flags({'value': 'test@example.org'}))
        self.assertIn('possible credential', privacy_flags({'value': 'api_key=not-a-real-key'}))
        self.assertIn('IP address', privacy_flags({'value': '192.0.2.1'}))

    def test_csv_formula_neutralization(self):
        plan = plan_fixture()
        plan['items'][0]['action'] = '  =1+1'
        output = export_csv({'reviewed_plan': plan, 'model': 'test', 'generated_at': 'test', 'reviewed_at': 'test'})
        self.assertIn("'  =1+1", output)

    def test_successful_gemini_transport(self):
        captured = {}
        def opener(request, timeout):
            captured.update(json.loads(request.data))
            self.assertEqual(timeout, 60)
            self.assertEqual(request.get_header('X-goog-api-key'), 'unit-test-not-a-key')
            self.assertNotIn('unit-test-not-a-key', request.full_url)
            self.assertIn('generativelanguage.googleapis.com', request.full_url)
            return io.BytesIO(json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(plan_fixture())}]}}]}).encode())
        result = generate_plan(input_fixture(), 'unit-test-not-a-key', 'gemini-test', opener)
        self.assertEqual(result, plan_fixture())
        self.assertEqual(captured['generationConfig']['responseMimeType'], 'application/json')
        self.assertIn('responseJsonSchema', captured['generationConfig'])

    def test_failure_modes(self):
        responses = [b'not json', b'{}',
            json.dumps({'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {'parts': [{'text': '{}'}]}}]}).encode(),
            json.dumps({'promptFeedback': {'blockReason': 'SAFETY'}}).encode(),
            json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"items":[]}'}]}}]}).encode(),
            b'x'*250001]
        for body in responses:
            with self.subTest(body=body[:50]), self.assertRaises(AIError):
                generate_plan(input_fixture(), 'unit-test-not-a-key', 'gemini-test', lambda *a, **k: io.BytesIO(body))

    def test_network_errors_do_not_leak_response_or_key(self):
        for error in [TimeoutError(), urllib.error.HTTPError('test', 401, 'sensitive-provider-message', {}, None),
                      urllib.error.HTTPError('test', 429, 'sensitive-provider-message', {}, None)]:
            def opener(*a, **k):
                raise error
            with self.assertRaises(AIError) as caught:
                generate_plan(input_fixture(), 'secret-key-value', 'gemini-test', opener)
            self.assertNotIn('secret-key-value', str(caught.exception))
            self.assertNotIn('sensitive-provider-message', str(caught.exception))

    def test_budget(self):
        budget = CallBudget()
        budget.reserve(1)
        with self.assertRaises(AIError):
            budget.reserve(1)


if __name__ == '__main__':
    unittest.main()
