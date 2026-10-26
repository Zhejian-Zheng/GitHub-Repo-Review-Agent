import unittest

from repo_review_agent.redaction import redact_data, redact_text


class RedactionTests(unittest.TestCase):
    def test_common_credentials_are_masked_and_safe_code_unchanged(self):
        values = [
            'ghp_' + 'a' * 36, 'sk-' + 'a' * 24,
            'AKIA' + 'A' * 16, 'eyJabc.def.signature',
            'Authorization: Bearer test-private-value',
            'https://name:secret@example.test/path',
            'password="test-secret"', "api_key = 'test-private'",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertIn('[REDACTED]', redact_text(value))
                self.assertNotEqual(redact_text(value), value)
        self.assertEqual(redact_text('def hello():\n    return 42'), 'def hello():\n    return 42')

    def test_multiline_private_key_keeps_source_line_numbers(self):
        source = 'start\n-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----\nend'
        masked = redact_text(source)
        self.assertEqual(len(masked.splitlines()), 5)
        self.assertEqual(masked.splitlines()[4], 'end')
        self.assertNotIn('private-material', masked)

    def test_nested_report_data_stays_typed(self):
        data = {'items': ['TOKEN=secret-value'], 'count': 2, 'enabled': True, 'empty': None}
        masked = redact_data(data)
        self.assertNotIn('secret-value', str(masked))
        self.assertEqual(masked['count'], 2)
        self.assertIs(masked['enabled'], True)
        self.assertIsNone(masked['empty'])

    def test_structured_secret_fields_masked_without_hiding_token_counts(self):
        data = {'password': 'plain-secret', 'nested': {'api_key': 'opaque-value'}, 'max_output_tokens': 900}
        masked = redact_data(data)
        self.assertEqual(masked['password'], '[REDACTED]')
        self.assertEqual(masked['nested']['api_key'], '[REDACTED]')
        self.assertEqual(masked['max_output_tokens'], 900)
