import json
import hashlib
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox, ValidationError
from courseinbox.desktop_alerts import DesktopAlerts
from courseinbox.mobile_reminders import MobileReminders
from courseinbox.chaoxing import ingest_web_message


class MobileReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.inbox=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.alerts=DesktopAlerts(self.inbox)
        self.sync=dict(enabled=True,inventory_epoch=0,sources={'task_center':{'discovered_sections':[]}})
        self.hub=MobileReminders(self.inbox,self.alerts,'a'*32,lambda:self.sync,port=0,listen_host='127.0.0.1')
        self.addCleanup(self.hub.close)
        self.hub.configure(True)

    def pair(self,name='测试手机',at='2026-10-20T09:00:00+08:00'):
        code=self.hub.make_pairing(at)['code']
        return self.hub.pair(code,name,at)

    def publish(self,text='《数据库》新作业，请完成报告。',at='2026-10-20T09:01:00+08:00',candidates=None):
        with patch('courseinbox.core.now_iso',return_value=at):
            return self.inbox.ingest(text,source='学习通课程通知',captured_at=at,candidates=candidates)

    def test_each_phone_and_desktop_have_independent_persistent_receipts(self):
        one=self.pair();two=self.pair('另一部手机')
        self.alerts.poll('2026-10-20T09:00:00+08:00')
        self.publish()
        desktop=self.alerts.poll('2026-10-20T09:02:00+08:00')['events'];self.alerts.ack([desktop[0]['id']])
        first=self.hub.poll(one['token'],'2026-10-20T09:02:00+08:00')['events']
        self.assertEqual(len(first),1)
        self.assertEqual(first,self.hub.poll(one['token'],'2026-10-20T09:03:00+08:00')['events'])
        self.hub.ack(one['token'],[first[0]['id']])
        self.assertEqual(self.hub.poll(one['token'],'2026-10-20T09:04:00+08:00')['events'],[])
        self.assertEqual(len(self.hub.poll(two['token'],'2026-10-20T09:04:00+08:00')['events']),1)
        self.hub.close()
        other=MobileReminders(self.inbox,self.alerts,'a'*32,lambda:self.sync,port=0,listen_host='127.0.0.1')
        self.addCleanup(other.close)
        self.assertEqual(other.poll(one['token'],'2026-10-20T09:05:00+08:00')['events'],[])

    def test_pairing_is_single_use_expires_and_is_rate_limited(self):
        code=self.hub.make_pairing('2026-10-20T09:00:00+08:00')['code']
        with self.assertRaises(ValidationError):self.hub.pair(code,'过期','2026-10-20T09:06:00+08:00')
        code=self.hub.make_pairing()['code'];self.hub.pair(code,'手机')
        with self.assertRaises(ValidationError):self.hub.pair(code,'重放')
        code=self.hub.make_pairing()['code']
        for _ in range(5):
            with self.assertRaises(ValidationError):self.hub.pair('not-a-code','猜测')
        with self.assertRaises(ValidationError):self.hub.pair(code,'超过限次')

    def test_pairing_primes_existing_backlog_and_late_old_publications(self):
        self.publish(at='2026-10-20T08:00:00+08:00')
        phone=self.pair()
        self.assertEqual(self.hub.poll(phone['token'],'2026-10-20T09:01:00+08:00')['events'],[])
        self.publish('《数学》补读的旧作业，请完成练习。','2026-10-19T08:00:00+08:00')
        self.assertEqual(self.hub.poll(phone['token'],'2026-10-20T09:02:00+08:00')['events'],[])

    def test_ordinary_learning_message_alerts_without_creating_a_task(self):
        phone=self.pair();self.publish('老师说今天的材料已更新。',candidates=[])
        result=self.hub.poll(phone['token'],'2026-10-20T09:02:00+08:00')['events']
        self.assertEqual(len(result),1);self.assertEqual(result[0]['kind'],'new_message')
        self.assertEqual(self.inbox.tasks(),[])

    def test_revoke_and_stop_make_old_tokens_unusable_and_status_has_no_secrets(self):
        phone=self.pair();encoded=json.dumps(self.hub.status())
        self.assertNotIn(phone['token'],encoded)
        self.hub.revoke(phone['device_id'])
        with self.assertRaises(PermissionError):self.hub.poll(phone['token'])
        phone=self.pair();self.hub.configure(False)
        with self.assertRaises(ValidationError):self.hub.poll(phone['token'])

    def test_ack_only_accepts_ids_actually_issued_to_that_device(self):
        phone=self.pair()
        with self.assertRaises(ValidationError):self.hub.ack(phone['token'],['proposal:forged'])
        self.publish();issued=self.hub.poll(phone['token'],'2026-10-20T09:02:00+08:00')['events'][0]['id']
        other=self.pair('后来配对','2026-10-20T09:03:00+08:00')
        with self.assertRaises(ValidationError):self.hub.ack(other['token'],[issued])

    def test_lan_listener_never_exposes_main_api_and_requires_device_token(self):
        base='http://127.0.0.1:'+str(self.hub.status()['port'])
        def request(path,body=None,token=None):
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer '+token
            req=urllib.request.Request(base+path,None if body is None else json.dumps(body).encode(),headers)
            try:
                with urllib.request.urlopen(req,timeout=4) as response:return response.status,json.loads(response.read())
            except urllib.error.HTTPError as error:return error.code,json.loads(error.read())
        self.assertEqual(request('/api/bootstrap')[0],404)
        self.assertEqual(request('/api/tasks')[0],404)
        self.assertEqual(request('/v1/alerts')[0],401)
        self.assertEqual(request('/v1/alerts',token='main-token-is-not-a-device-token')[0],401)
        code=self.hub.make_pairing()['code'];status,phone=request('/v1/pair',dict(code=code,name='手机'))
        self.assertEqual(status,200)
        self.assertEqual(request('/v1/alerts',token=phone['token'])[0],200)
        self.assertEqual(request('/v1/ack',dict(ids=['fake']),phone['token'])[0],400)

    def test_desktop_baseline_or_disabling_desktop_alerts_cannot_consume_phone_events(self):
        phone=self.pair();self.publish()
        self.assertEqual(self.alerts.poll('2026-10-20T09:02:00+08:00')['events'],[])
        self.alerts.settings(False)
        self.assertEqual(len(self.hub.poll(phone['token'],'2026-10-20T09:03:00+08:00')['events']),1)

    def test_initial_task_inventory_is_baselined_per_phone_then_new_task_alerts(self):
        phone=self.pair()
        section=hashlib.sha256(b'1|2|assignment').hexdigest()[:24]
        def job(number,at):
            return dict(kind='task_center',message_id='inventory_'+str(number),title='作业'+str(number),text='请提交报告',course='数据库',conversation='一班',captured_at=at,
                        url=f'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId={number}')
        ingest_web_message(self.inbox,job(1,'2026-10-20T09:01:00+08:00'))
        self.sync['sources']['task_center'].update(discovered_sections=[section],discovered_section_times={section:'2026-10-20T09:01:30+08:00'})
        self.assertEqual(self.hub.poll(phone['token'],'2026-10-20T09:02:00+08:00')['events'],[])
        ingest_web_message(self.inbox,job(2,'2026-10-20T09:03:00+08:00'))
        events=self.hub.poll(phone['token'],'2026-10-20T09:04:00+08:00')['events']
        self.assertEqual(len(events),1);self.assertIn('作业2',events[0]['body'])

    def test_existing_confirmed_task_can_generate_later_deadline_threshold(self):
        result=self.publish('《数学》作业：请完成报告，截止2026年10月21日12:00。','2026-10-20T08:00:00+08:00')
        self.inbox.confirm(result['proposals'][0]['id'])
        phone=self.pair()
        self.assertEqual(self.hub.poll(phone['token'],'2026-10-20T09:01:00+08:00')['events'],[])
        events=self.hub.poll(phone['token'],'2026-10-21T10:01:00+08:00')['events']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['kind'],'deadline_due')

    def test_offline_phone_still_learns_new_task_confirmed_on_computer(self):
        phone=self.pair();result=self.publish()
        self.inbox.confirm(result['proposals'][0]['id'])
        events=self.hub.poll(phone['token'],'2026-10-20T09:03:00+08:00')['events']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['id'],'proposal:'+result['proposals'][0]['id'])
        self.assertNotIn('待确认',events[0]['title'])

    def test_offline_first_poll_does_not_baseline_tasks_published_after_initial_inventory(self):
        phone=self.pair();section=hashlib.sha256(b'1|2|assignment').hexdigest()[:24]
        def capture(number,at):
            ingest_web_message(self.inbox,dict(kind='task_center',message_id='offline_inventory_'+str(number),title='作业'+str(number),text='请交报告',course='数据库',conversation='一班',captured_at=at,url=f'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId={number}'))
        capture(1,'2026-10-20T09:01:00+08:00')
        self.sync['sources']['task_center'].update(discovered_sections=[section],discovered_section_times={section:'2026-10-20T09:02:00+08:00'})
        capture(2,'2026-10-20T10:01:00+08:00')
        events=self.hub.poll(phone['token'],'2026-10-20T10:02:00+08:00')['events']
        self.assertEqual(len(events),1);self.assertIn('作业2',events[0]['body'])

    def test_stale_discovery_snapshot_cannot_consume_tasks_received_before_poll_lock(self):
        phone=self.pair();section=hashlib.sha256(b'1|2|assignment').hexdigest()[:24]
        def capture(number,at):
            return ingest_web_message(self.inbox,dict(kind='task_center',message_id='racing_inventory_'+str(number),title='作业'+str(number),text='请交报告',course='数据库',conversation='一班',captured_at=at,url=f'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId={number}'))
        capture(1,'2026-10-20T09:01:00+08:00')
        stale=json.loads(json.dumps(self.sync))
        def finish_inventory_before_poll_acquires_inbox_lock():
            # Model the scanner advancing after status() copied its snapshot,
            # while poll is still waiting to read the inbox.
            self.sync['sources']['task_center'].update(discovered_sections=[section],discovered_section_times={section:'2026-10-20T09:02:00+08:00'})
            capture(2,'2026-10-20T09:02:01+08:00')
            return stale
        with patch.object(self.hub,'sync_status',side_effect=finish_inventory_before_poll_acquires_inbox_lock):
            self.assertEqual(self.hub.poll(phone['token'],'2026-10-20T09:01:59+08:00')['events'],[])
        with self.inbox.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mobile_reminder_receipts WHERE device_id=?',(phone['device_id'],)).fetchone()[0],0)
        events=self.hub.poll(phone['token'],'2026-10-20T09:02:02+08:00')['events']
        self.assertEqual(len(events),1);self.assertIn('作业2',events[0]['body'])
        self.hub.ack(phone['token'],[events[0]['id']])
        self.assertEqual(self.hub.poll(phone['token'],'2026-10-20T09:03:00+08:00')['events'],[])

    def test_incomplete_headers_are_closed_without_waiting_for_authentication(self):
        peer=socket.create_connection(('127.0.0.1',self.hub.status()['port']),timeout=10)
        self.addCleanup(peer.close)
        peer.sendall(b'GET /v1/health HTTP/1.1\r\nHost:')
        self.assertEqual(peer.recv(1),b'')

    def test_phone_browser_page_and_only_fixed_assets_are_available_without_main_token(self):
        base='http://127.0.0.1:'+str(self.hub.status()['port'])
        for path,kind,marker in (('/', 'text/html',b'phone.js'),('/phone.js','text/javascript',b'/v1/pair'),('/phone.css','text/css',b'font-family')):
            with urllib.request.urlopen(base+path) as response:
                self.assertIn(kind,response.headers['Content-Type'])
                self.assertIn(marker,response.read())
                self.assertEqual(response.headers['X-Frame-Options'],'DENY')
        for path in ('/app.js','/api/state','/../server.py'):
            with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(base+path)
            self.assertEqual(raised.exception.code,404)


if __name__=='__main__':unittest.main()
