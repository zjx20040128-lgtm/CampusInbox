import unittest
import tempfile
import urllib.request
from pathlib import Path
from server import browser_url
from courseinbox.core import Inbox
from courseinbox.http import create_server


class ServerLauncherTests(unittest.TestCase):
    def test_isolated_server_can_assign_a_separate_ephemeral_reminder_port(self):
        with tempfile.TemporaryDirectory() as directory:
            box=Inbox(Path(directory)/'inbox.sqlite3')
            server=create_server('127.0.0.1',0,box,'isolated-server-reminder-test-token',reminder_port=0)
            try:
                settings=server.mobile_reminders.configure(True)
                self.assertTrue(settings['listening'])
                self.assertGreater(settings['port'],0)
                with urllib.request.urlopen('http://127.0.0.1:'+str(settings['port'])+'/',timeout=5) as response:
                    self.assertEqual(response.status,200)
            finally:server.server_close()

    def test_browser_url_keeps_default_home_and_supports_fixed_sync_view(self):
        self.assertEqual(browser_url(8765,'today'),'http://127.0.0.1:8765')
        self.assertEqual(browser_url(8877,'sync'),'http://127.0.0.1:8877/#sync')
        with self.assertRaises(ValueError):browser_url(8765,'https://evil.example')


if __name__=='__main__':
    unittest.main()
