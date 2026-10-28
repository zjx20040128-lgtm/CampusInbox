import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path
from courseinbox.core import Inbox,now_iso
from courseinbox.desktop_alerts import DesktopAlerts
from courseinbox.mobile_reminders import MobileReminders


class MobilePushTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.hub=MobileReminders(self.box,DesktopAlerts(self.box),'a'*32,lambda:{'enabled':False},port=0,listen_host='127.0.0.1')
        self.hub.configure(True);self.addCleanup(self.hub.close)
        self.session=self.hub.pair(self.hub.make_pairing()['code'],'推送测试手机')

    def connect(self,token):
        c=http.client.HTTPConnection('127.0.0.1',self.hub.server.server_port,timeout=3);self.addCleanup(c.close)
        c.request('GET','/v1/stream',headers={'Authorization':'Bearer '+token});return c.getresponse()

    def frame(self,response):
        while True:
            line=response.readline()
            if not line:raise AssertionError('stream closed unexpectedly')
            if line.startswith(b'data: '):return json.loads(line[6:])

    def test_authenticated_stream_pushes_after_commit_without_client_polling(self):
        response=self.connect(self.session['token']);self.assertEqual(response.status,200)
        self.assertEqual(response.headers['Content-Type'],'text/event-stream; charset=utf-8')
        self.assertEqual(self.frame(response)['events'],[])
        start=time.monotonic()
        self.box.ingest('推送验证：课程资料已更新。',source='学习通课程通知',captured_at=now_iso())
        batch=self.frame(response);self.assertLess(time.monotonic()-start,3)
        self.assertIn('推送验证',batch['events'][0]['body'])
        self.hub.ack(self.session['token'],[batch['events'][0]['id']])
        self.assertEqual(self.hub.poll(self.session['token'])['events'],[])

    def test_unpaired_stream_rejected_and_revocation_closes_existing_pair(self):
        self.assertEqual(self.connect('wrong-token').status,401)
        response=self.connect(self.session['token']);self.assertEqual(response.status,200);self.frame(response)
        self.hub.revoke(self.session['device_id'])
        self.assertEqual(self.frame(response).get('error'),'revoked')

    def test_change_notifications_fire_only_after_successful_commit(self):
        seen=[];remove=self.box.subscribe_changes(lambda:seen.append(True));self.addCleanup(remove)
        with self.box.connection() as db:db.execute('CREATE TABLE push_commit_check(value TEXT)')
        with self.assertRaises(RuntimeError):
            with self.box.connection() as db:
                db.execute("INSERT INTO push_commit_check VALUES('rolled-back')");raise RuntimeError('rollback')
        self.assertEqual(seen,[])
        with self.box.connection() as db:db.execute("INSERT INTO push_commit_check VALUES('committed')")
        self.assertEqual(seen,[True])


if __name__=='__main__':unittest.main()
