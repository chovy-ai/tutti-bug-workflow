"""Token import verifies identity before replacing private CLI credentials."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workbench_token_test', ROOT / 'scripts/workbench.py')
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)


class TuttiTokenTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.data = self.home / 'workbench'
        self.data.mkdir()
        self.target = self.home / '.config/tutti-ops/config.json'
        self.target.parent.mkdir(parents=True)
        self.before = {'token': 'old-secret', 'adminUrl': 'https://old.example.com', 'custom': 42}
        self.target.write_text(json.dumps(self.before))
        self.config = json.loads((ROOT / 'config/workbench.example.json').read_text())
        (self.data / 'config.json').write_text(json.dumps(self.config))
        self.args = SimpleNamespace(config=None, admin_url='https://admin.tutti.sh', token_stdin=True, token_env=False)
        self.token = 'synthetic-new-secret'
        self.success = subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'meta': {'executed': True}, 'token': self.token}), '')
        for p in [patch.object(workbench.Path, 'home', return_value=self.home),
                  patch.object(workbench, 'installed_command', return_value='/synthetic/tutti-ops')]:
            p.start()
            self.addCleanup(p.stop)

    def invoke(self, response=None, error=None):
        with patch('sys.stdin', io.StringIO(self.token + '\n')), \
                patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch.object(workbench.subprocess, 'run', return_value=response or self.success, side_effect=error) as run:
            workbench.configure_tutti_token(self.args, self.data)
        return json.loads(output.getvalue()), run

    def test_verified_token_saved_privately_without_secret_in_arguments_or_receipt(self):
        with patch.dict(os.environ, {'TUTTI_ADMIN_COOKIE': 'synthetic-cookie'}):
            report, run = self.invoke()
        command = run.call_args.args[0]
        self.assertNotIn(self.token, command)
        self.assertEqual(run.call_args.kwargs['env']['TUTTI_ADMIN_TOKEN'], self.token)
        self.assertNotIn('TUTTI_ADMIN_COOKIE', run.call_args.kwargs['env'])
        self.assertIn('--metadata-only', command)
        saved = json.loads(self.target.read_text())
        self.assertEqual(saved, {**self.before, 'token': self.token, 'adminUrl': self.args.admin_url})
        if os.name != 'nt':
            self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(report['authentication'], 'authenticated')
        self.assertEqual(report['business_logs_access'], 'not_checked')
        self.assertNotIn(self.token, json.dumps(report))
        for file in self.data.rglob('*.json'):
            self.assertNotIn(self.token, file.read_text())

    def test_rejected_token_preserves_existing_credentials_and_hides_raw_errors(self):
        response = subprocess.CompletedProcess([], 3, self.token, 'upstream echoed ' + self.token)
        with self.assertRaises(ValueError) as failure:
            self.invoke(response)
        self.assertNotIn(self.token, str(failure.exception))
        self.assertEqual(json.loads(self.target.read_text()), self.before)
        self.assertFalse((self.data / 'connections/tutti-ops-auth.json').exists())

    def test_zero_exit_with_unexecuted_or_invalid_response_is_not_authentication(self):
        for body in ['{}', '[]', '{"ok":false}', '{"ok":true,"meta":{"executed":false}}', 'not json']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.invoke(subprocess.CompletedProcess([], 0, body, ''))
            self.assertEqual(json.loads(self.target.read_text()), self.before)

    def test_timeout_does_not_expose_output_or_replace_credentials(self):
        with self.assertRaises(ValueError) as failure:
            self.invoke(error=subprocess.TimeoutExpired(['tutti-ops'], 40, output=self.token))
        self.assertNotIn(self.token, str(failure.exception))
        self.assertEqual(json.loads(self.target.read_text()), self.before)

    def test_environment_import_and_hidden_terminal_input(self):
        self.args.token_stdin = False
        self.args.token_env = True
        with patch.dict(os.environ, {'TUTTI_ADMIN_TOKEN': self.token}):
            self.invoke()
        self.assertEqual(json.loads(self.target.read_text())['token'], self.token)
        self.args.token_env = False
        with patch('sys.stdin.isatty', return_value=True), \
                patch.object(workbench.getpass, 'getpass', return_value='hidden-secret') as prompt, \
                patch.object(workbench.subprocess, 'run', return_value=self.success), \
                patch('sys.stdout', new_callable=io.StringIO):
            workbench.configure_tutti_token(self.args, self.data)
        prompt.assert_called_once()
        self.assertEqual(json.loads(self.target.read_text())['token'], 'hidden-secret')

    def test_missing_cli_empty_token_and_unsafe_origin_fail_before_network(self):
        with patch.object(workbench, 'installed_command', return_value=None), self.assertRaises(ValueError):
            self.invoke()
        for token in ['', 'two tokens', 'x' * 16385]:
            self.token = token
            with self.subTest(token_length=len(token)), self.assertRaises(ValueError):
                self.invoke()
        self.token = 'synthetic-secret'
        for origin in ['http://remote.example.com', 'https://user:secret@example.com', 'https://example.com/path']:
            self.args.admin_url = origin
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(json.loads(self.target.read_text()), self.before)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink fixture')
    def test_symlink_credentials_are_not_overwritten(self):
        other = self.home / 'other.json'
        other.write_text(json.dumps(self.before))
        self.target.unlink()
        self.target.symlink_to(other)
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(json.loads(other.read_text()), self.before)


if __name__ == '__main__':
    unittest.main()
