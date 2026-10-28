import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox
from courseinbox.http import create_server


class DesktopFeatureApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.inbox=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.token='isolated-desktop-feature-test-token'
        self.server=create_server('127.0.0.1',0,self.inbox,self.token)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,path,body=None,auth=True):
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer '+self.token
        request=urllib.request.Request(self.url+path,None if body is None else json.dumps(body).encode(),headers)
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:return error.code,json.loads(error.read())

    def test_page_preview_and_cleanup_snapshot_keep_newer_arrival(self):
        old=self.inbox.ingest('普通旧通知',captured_at='2026-10-15T09:00:00+08:00')['message']
        code,page=self.request('/api/messages/page?limit=1&offset=0')
        self.assertEqual(code,200)
        self.assertEqual(page['total'],1)
        code,snapshot=self.request('/api/messages/cleanup-preview')
        self.assertEqual(code,200)
        fresh=self.inbox.ingest('普通新通知',captured_at='2026-10-16T09:00:00+08:00')['message']
        code,result=self.request('/api/messages/clear',dict(ids=snapshot['ids']))
        self.assertEqual(code,200)
        self.assertEqual(result['cleared'],1)
        self.assertEqual(self.request('/api/messages/page')[1]['items'][0]['id'],fresh['id'])
        self.assertEqual(self.request('/api/messages/clear',dict(ids=[old['id'],'bad']))[0],400)
        self.assertEqual(self.request('/api/messages/page?limit=0')[0],400)

    def test_alert_contract_and_scope_authentication(self):
        self.assertEqual(self.request('/api/desktop/alerts',auth=False)[0],401)
        code,result=self.request('/api/desktop/alerts')
        self.assertEqual(code,200)
        self.assertTrue(result['enabled'])
        self.assertEqual(result['events'],[])
        self.assertEqual(self.request('/api/desktop/alerts/settings',dict(enabled=False))[1],dict(enabled=False))
        self.assertFalse(self.request('/api/desktop/alerts')[1]['enabled'])
        self.assertEqual(self.request('/api/desktop/alerts/settings',dict(enabled='false'))[0],400)
        self.assertEqual(self.request('/api/desktop/alerts/ack',dict(ids=['proposal:abc']))[1],dict(ok=True))
        self.assertEqual(self.request('/api/desktop/alerts/ack',dict(ids=['../../evil']))[0],400)

    def test_hidden_pending_message_can_be_opened_and_exported_as_evidence(self):
        result=self.inbox.ingest('《数学》第一次作业，请完成报告。',captured_at='2026-10-16T09:00:00+08:00')
        self.inbox.clear_messages([result['message']['id']])
        self.assertEqual(self.request('/api/messages/'+result['message']['id'])[1]['text'],result['message']['text'])
        self.assertEqual(len(self.request('/api/export.json')[1]['messages']),1)

    def test_recheck_uses_existing_session_without_fresh_login(self):
        with patch.object(self.server.desktop_sync,'recheck',return_value={'state':'retrying'}) as recheck:
            self.assertEqual(self.request('/api/chaoxing/desktop/recheck',{})[0],200)
            recheck.assert_called_once_with()
            self.assertEqual(self.request('/api/chaoxing/desktop/recheck',dict(visible=True))[0],400)

    def test_inventory_and_repair_require_main_token_and_validate_body(self):
        self.assertEqual(self.request('/api/chaoxing/desktop/inventory',auth=False)[0],401)
        code,report=self.request('/api/chaoxing/desktop/inventory?limit=20&offset=0')
        self.assertEqual(code,200)
        self.assertEqual(report['total'],0)
        self.assertTrue(report['catalog_limited'])
        self.assertEqual(self.request('/api/chaoxing/desktop/inventory?limit=0')[0],400)
        self.assertEqual(self.request('/api/chaoxing/desktop/repair',{})[0],400)
        self.server.desktop_sync.enabled=True
        self.assertEqual(self.request('/api/chaoxing/desktop/repair',{})[1]['requested'],0)
        self.assertEqual(self.request('/api/chaoxing/desktop/repair',dict(keys=['fake']))[0],400)
        self.assertEqual(self.request('/api/chaoxing/desktop/repair',dict(url='https://example.com'))[0],400)

    def test_mobile_reminder_controls_require_main_auth_and_cannot_open_main_lan_api(self):
        self.assertEqual(self.request('/api/mobile-reminders/status',auth=False)[0],401)
        self.assertEqual(self.request('/api/mobile-reminders/status')[1]['listening'],False)
        self.assertEqual(self.request('/api/mobile-reminders/pairing',{})[0],400)
        self.assertEqual(self.request('/api/mobile-reminders/settings',dict(enabled='yes'))[0],400)
        self.server.mobile_reminders.port=0
        code,status=self.request('/api/mobile-reminders/settings',dict(enabled=True))
        self.assertEqual(code,200);self.assertTrue(status['listening'])
        self.assertGreater(status['port'],0)
        self.assertNotEqual(status['port'],self.server.server_port)
        code,pairing=self.request('/api/mobile-reminders/pairing',{})
        self.assertEqual(code,200);self.assertRegex(pairing['code'],r'^\d{6}$')
        self.assertEqual(self.request('/api/mobile-reminders/settings',dict(enabled=False))[1]['listening'],False)


if __name__=='__main__':unittest.main()
