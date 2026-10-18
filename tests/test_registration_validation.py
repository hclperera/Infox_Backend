import unittest

from services.registration_validation import is_valid_registration_email, registration_error


class RegistrationValidationTests(unittest.TestCase):
    def test_accepts_plus_and_long_domains(self):
        for email in ('reader+notes@example.com', 'reader@example.technology',
                      'first.last@sub.example.co.uk'):
            with self.subTest(email=email):
                self.assertTrue(is_valid_registration_email(email))

    def test_rejects_malformed_addresses(self):
        for email in ('a@@example.com', 'a b@example.com', '.a@example.com',
                      'a..b@example.com', 'a@example..com', 'a@-example.com',
                      'a@example.com\n', 'a@example', 'a@exa_mple.com'):
            with self.subTest(email=email):
                self.assertFalse(is_valid_registration_email(email))

    def test_required_fields_and_password_policy(self):
        self.assertEqual(registration_error(' ', '', ''), 'Please enter your username.')
        self.assertEqual(registration_error('reader', ' ', ''), 'Please enter your email.')
        self.assertEqual(registration_error('reader', 'a@example.com', ''), 'Please enter your password.')
        self.assertIsNone(registration_error(' reader ', ' a@example.com ', ' weak password '))
        self.assertEqual(registration_error('reader', 'bad', 'pass'), 'Please enter a valid email address.')


if __name__ == '__main__':
    unittest.main()
