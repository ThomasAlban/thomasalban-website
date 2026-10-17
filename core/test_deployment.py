"""Deployment probes use temporary media and the test database only."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from deploy.admin_gate import gate_record

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings


class AdminGateTests(SimpleTestCase):
    def test_missing_and_unsafe_credentials_rejected_before_hashing(self):
        valid = {'ADMIN_GATE_USERNAME': 'admin-test', 'ADMIN_GATE_PASSWORD': 'test-only-password-0123456789'}
        for name, value in (
            ('ADMIN_GATE_USERNAME', ''), ('ADMIN_GATE_USERNAME', 'name:injection'),
            ('ADMIN_GATE_USERNAME', 'name\nother'), ('ADMIN_GATE_PASSWORD', ''),
            ('ADMIN_GATE_PASSWORD', 'short'), ('ADMIN_GATE_PASSWORD', 'x' * 129),
            ('ADMIN_GATE_PASSWORD', 'x' * 24 + '\n'),
        ):
            with self.subTest(name=name, value=value), patch('deploy.admin_gate.subprocess.run') as run:
                with self.assertRaises(ValueError):
                    gate_record({**valid, name: value})
                run.assert_not_called()

    def test_password_only_passed_via_stdin_and_hash_returned(self):
        secret = 'test-only-password-0123456789'
        with patch('deploy.admin_gate.subprocess.run', return_value=Mock(
            returncode=0, stdout='$6$randomsalt$hashvalue\n',
        )) as run:
            record = gate_record({'ADMIN_GATE_USERNAME': 'test-admin', 'ADMIN_GATE_PASSWORD': secret})
        self.assertEqual(record, 'test-admin:$6$randomsalt$hashvalue\n')
        self.assertNotIn(secret, repr(run.call_args.args))
        self.assertEqual(run.call_args.kwargs['input'], secret + '\n')
        self.assertEqual(run.call_args.kwargs['env'], {'PATH': '/usr/bin:/bin'})

    def test_hash_failure_is_generic(self):
        with patch('deploy.admin_gate.subprocess.run', return_value=Mock(
            returncode=1, stdout='sensitive output',
        )):
            with self.assertRaisesMessage(ValueError, 'Admin gate password hashing failed.'):
                gate_record({'ADMIN_GATE_USERNAME': 'test-admin', 'ADMIN_GATE_PASSWORD': 'x' * 24})

    def test_proxy_strips_authorization_and_gate_cannot_be_bypassed_by_regex(self):
        root = Path(__file__).resolve().parent.parent
        self.assertIn('proxy_set_header Authorization "";', (root / 'deploy/proxy.conf').read_text())
        config = (root / 'deploy/nginx.conf').read_text()
        self.assertIn('location ^~ /admin {', config)
        self.assertIn('auth_basic_user_file /run/admin-gate/htpasswd;', config)



class ReadinessTests(TestCase):
    def test_ready_and_not_cacheable(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=Path(directory)):
            response = self.client.get('/healthz/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b'ok')
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(response['X-Robots-Tag'], 'noindex')
            self.assertEqual(self.client.head('/healthz/').status_code, 200)

    def test_missing_media_is_unavailable(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=Path(directory) / 'absent'):
            self.assertEqual(self.client.get('/healthz/').status_code, 503)

    def test_database_failure_does_not_leak_details(self):
        with patch('config.health.connection.cursor', side_effect=OperationalError('private path')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'unavailable')

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post('/healthz/').status_code, 405)
