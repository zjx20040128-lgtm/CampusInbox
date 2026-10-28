import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from courseinbox.core import Inbox,CN
from courseinbox.http import create_server,seed_demo

TOKEN='test-token-which-is-long-and-not-a-real-secret'
AT='2026-10-03T16:00:00+08:00'

class ApiTests(unittest.TestCase):
    def test_supplement_is_authenticated_scoped_and_draft_only(self):
        status,raw,_=self.request('/api/messages','POST',{'text':'《补充API课程》实验三，请提交报告。','captured_at':AT})
        self.assertEqual(status,201)
        original=json.loads(raw)['message'];path='/api/messages/'+original['id']+'/supplements'
        self.assertEqual(self.request(path,auth=False)[0],401)
        status,raw,_=self.request(path)
        self.assertEqual(status,200);target=json.loads(raw)['targets'][0]['key']
        before=len(self.inbox.tasks())
        status,raw,_=self.request(path,'POST',{'text':'请同时提交源代码。','target':target})
        self.assertEqual(status,201);result=json.loads(raw)
        self.assertEqual(len(self.inbox.tasks()),before)
        self.assertEqual(self.inbox.message(original['id'])['text'],original['text'])
        self.assertEqual(len(result['proposals']),1)
        self.assertEqual(self.request(path,'POST',{'text':'请同时提交源代码。','target':target})[0],200)
        self.assertEqual(self.request(path,'POST',{'text':'未知字段','target':target,'source_url':'https://evil.example'})[0],400)
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.inbox=Inbox(Path(cls.tmp.name)/'db.sqlite3')
        cls.server=create_server('127.0.0.1',0,cls.inbox,TOKEN,root=Path(__file__).resolve().parents[1])
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()
    def request(self,path,method='GET',body=None,auth=True,headers=None):
        h={'Content-Type':'application/json'}
        if auth: h['Authorization']='Bearer '+TOKEN
        h.update(headers or {})
        raw=None if body is None else json.dumps(body).encode()
        r=urllib.request.Request(self.url+path,raw,h,method=method)
        try:
            with urllib.request.urlopen(r,timeout=5) as response:
                return response.status,response.read(),response.headers
        except urllib.error.HTTPError as error:
            return error.code,error.read(),error.headers
    def test_pairing_proof_is_readonly_and_requires_strict_challenge(self):
        from unittest.mock import patch
        from courseinbox.discovery import make_proof
        challenge='a'*64
        status,body,_=self.request('/api/mobile/pairing?challenge='+challenge,auth=False)
        self.assertEqual(status,200)
        result=json.loads(body)
        expected=make_proof(self.server.discovery.identity,TOKEN,challenge,'127.0.0.1',self.server.server_port)
        self.assertEqual(result,expected)
        self.assertNotIn(TOKEN,body.decode())
        for query in ['', '?challenge=', '?challenge='+('A'*64), '?challenge='+('a'*63), '?challenge='+('a'*1000), '?challenge='+challenge+'&challenge='+challenge]:
            self.assertEqual(self.request('/api/mobile/pairing'+query,auth=False)[0],400)
        self.assertEqual(self.request('/api/mobile/pairing?challenge='+challenge,auth=False,headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/mobile/pairing?challenge='+challenge,auth=False,headers={'Origin':'http://evil.example'})[0],403)
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
        with patch('courseinbox.discovery.local_ipv4',return_value={'10.1.2.3'}):
            self.server.discovery.refresh_addresses()
            self.assertEqual(self.request('/api/health',auth=False,headers={'Host':'10.1.2.3:'+str(self.server.server_port)})[0],200)
        with patch('courseinbox.discovery.local_ipv4',return_value={'10.1.2.4'}):
            self.server.discovery.refresh_addresses()
            self.assertEqual(self.request('/api/health',auth=False,headers={'Host':'10.1.2.4:'+str(self.server.server_port)})[0],200)
            self.assertEqual(self.request('/api/health',auth=False,headers={'Host':'10.1.2.3:'+str(self.server.server_port)})[0],403)
        self.server.discovery.refresh_addresses()

    def test_no_token_cannot_read_or_write_student_data(self):
        for path,method,body in [('/api/tasks','GET',None),('/api/messages','POST',{'text':'课程作业'})]:
            self.assertEqual(self.request(path,method,body,auth=False)[0],401)
    def test_loopback_bootstrap_and_host_origin_checks(self):
        status,body,h=self.request('/api/bootstrap',auth=False)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['token'],TOKEN)
        self.assertEqual(h['Cache-Control'],'no-store')
        self.assertEqual(self.request('/api/bootstrap',auth=False,headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/tasks',headers={'Origin':'https://evil.example'})[0],403)
    def test_invalid_json_and_payloads_are_client_errors(self):
        for body in [[],{'text':''},{'text':'实验报告','captured_at':'昨天'},{'text':'a'*30001}]:
            self.assertEqual(self.request('/api/messages','POST',body)[0],400)
    def test_text_proposal_confirm_and_calendar_are_real(self):
        status,body,_=self.request('/api/messages','POST',{'text':'《高等数学》 第一次作业截止10月13日20:00。','captured_at':AT,'scope':'API班'})
        self.assertEqual(status,201)
        p=json.loads(body)['proposals'][0]
        status,body,_=self.request('/api/proposals/'+p['id']+'/confirm','POST',{})
        self.assertEqual(status,200)
        task=json.loads(body)
        status,body,_=self.request('/api/tasks/'+task['id'],'PATCH',{'status':'submitted','expected_version':task['version']})
        self.assertEqual(json.loads(body)['status'],'submitted')
        status,body,h=self.request('/api/calendar.ics')
        self.assertEqual(status,200)
        self.assertIn('BEGIN:VEVENT',body.decode())
        self.assertIn('text/calendar',h['Content-Type'])
    def test_android_whitelist_and_replayed_event(self):
        payload={'package_name':'com.chaoxing.mobile','notification_key':'test:key:1','title':'《软件工程》 第三次作业','text':'截止10月12日23:59。','captured_at':AT,'scope':'手机班'}
        status,body,_=self.request('/api/mobile/notifications','POST',payload)
        self.assertEqual(status,201)
        self.assertEqual(json.loads(body)['message']['source'],'Android · com.chaoxing.mobile')
        status,body,_=self.request('/api/mobile/notifications','POST',payload)
        self.assertEqual(status,200)
        self.assertTrue(json.loads(body)['duplicate'])
        payload['package_name']='com.private.chat'
        self.assertEqual(self.request('/api/mobile/notifications','POST',payload)[0],403)
    def test_mobile_timestamp_is_required_for_relative_deadline(self):
        payload={'package_name':'com.chaoxing.mobile','notification_key':'missing-time','title':'《高等数学》 第一次作业','text':'明天截止'}
        self.assertEqual(self.request('/api/mobile/notifications','POST',payload)[0],400)
    def test_stale_draft_can_be_rebuilt_against_current_version(self):
        initial={'text':'《复核恢复》 第一次作业截止10月12日18:00。','captured_at':AT,'scope':'刷新班','source':'API通知'}
        _,raw,_=self.request('/api/messages','POST',initial)
        original=json.loads(raw)
        _,raw,_=self.request('/api/proposals/'+original['proposals'][0]['id']+'/confirm','POST',{})
        task=json.loads(raw)
        initial['text']='《复核恢复》 第一次作业延期到10月14日18:00。'
        initial['captured_at']='2026-10-04T09:00:00+08:00'
        _,raw,_=self.request('/api/messages','POST',initial)
        extension=json.loads(raw)
        self.request('/api/tasks/'+task['id'],'PATCH',{'status':'in_progress','expected_version':task['version']})
        self.assertEqual(self.request('/api/proposals/'+extension['proposals'][0]['id']+'/confirm','POST',{})[0],409)
        code,raw,_=self.request('/api/messages/'+extension['message']['id']+'/reanalyze','POST',{})
        self.assertEqual(code,200)
        rebuilt=json.loads(raw)
        self.assertEqual(rebuilt['message']['id'],extension['message']['id'])
        _,raw,_=self.request('/api/proposals/'+rebuilt['proposals'][0]['id']+'/confirm','POST',{})
        result=json.loads(raw)
        self.assertEqual(result['deadline'],'2026-10-14T18:00:00+08:00')
        self.assertEqual(result['status'],'in_progress')
    def test_missing_resource_is_404_not_server_error(self):
        self.assertEqual(self.request('/api/tasks/nonexistent')[0],404)
    def test_encoded_traversal_cannot_read_local_db(self):
        self.assertEqual(self.request('/..%2fdata%2finbox.sqlite3')[0],404)

if __name__=='__main__': unittest.main()


class ApkDownloadTests(unittest.TestCase):
    def test_only_named_companion_apk_can_be_downloaded_without_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mobile=root/'artifacts'/'mobile';mobile.mkdir(parents=True)
            (mobile/'courseinbox-companion-0.2.3-debug.apk').write_bytes(b'fake-apk-fixture')
            (mobile/'courseinbox-companion-0.2.4-debug.apk').write_bytes(b'new-apk-fixture')
            (mobile/'courseinbox-companion-0.2.5-debug.apk').write_bytes(b'redesigned-apk-fixture')
            (mobile/'courseinbox-learning-0.3.0-debug.apk').write_bytes(b'standalone-mobile-apk-fixture')
            (mobile/'courseinbox-learning-0.3.1-debug.apk').write_bytes(b'mobile-login-ui-apk-fixture')
            (mobile/'courseinbox-learning-0.3.2-debug.apk').write_bytes(b'mobile-login-footer-apk-fixture')
            (mobile/'courseinbox-learning-0.3.3-debug.apk').write_bytes(b'mobile-login-policy-text-apk-fixture')
            (mobile/'courseinbox-learning-0.3.4-debug.apk').write_bytes(b'mobile-page-layout-apk-fixture')
            (mobile/'courseinbox-learning-0.3.5-debug.apk').write_bytes(b'mobile-image-https-apk-fixture')
            (mobile/'courseinbox-learning-0.3.8-debug.apk').write_bytes(b'mobile-alert-apk-fixture')
            (mobile/'courseinbox-learning-0.3.9-debug.apk').write_bytes(b'mobile-recovery-apk-fixture')
            (mobile/'courseinbox-learning-0.3.15-debug.apk').write_bytes(b'mobile-connection-timing-apk-fixture')
            (mobile/'courseinbox-learning-0.3.16-debug.apk').write_bytes(b'mobile-notice-body-apk-fixture')
            (mobile/'courseinbox-learning-0.3.17-debug.apk').write_bytes(b'mobile-source-flow-apk-fixture')
            (mobile/'courseinbox-learning-0.3.18-debug.apk').write_bytes(b'mobile-history-filter-apk-fixture')
            (mobile/'courseinbox-learning-0.3.19-debug.apk').write_bytes(b'mobile-inbox-cleanup-apk-fixture')
            (mobile/'courseinbox-learning-0.3.20-debug.apk').write_bytes(b'mobile-arm-apk-fixture')
            (mobile/'courseinbox-learning-0.3.20-arm64-debug.apk').write_bytes(b'mobile-arm64-apk-fixture')
            (mobile/'courseinbox-learning-0.3.20-universal-debug.apk').write_bytes(b'mobile-universal-apk-fixture')
            (mobile/'private.txt').write_text('not downloadable')
            server=create_server('127.0.0.1',0,Inbox(root/'data'/'inbox.sqlite3'),TOKEN,root=root)
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                url='http://127.0.0.1:'+str(server.server_port)
                with urllib.request.urlopen(url+'/downloads/courseinbox-companion-0.2.3-debug.apk') as response:
                    self.assertEqual(response.read(),b'fake-apk-fixture')
                    self.assertEqual(response.headers.get_content_type(),'application/vnd.android.package-archive')
                    self.assertIn('attachment',response.headers['Content-Disposition'])
                with urllib.request.urlopen(url+'/downloads/courseinbox-companion-0.2.4-debug.apk') as response:
                    self.assertEqual(response.read(),b'new-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-companion-0.2.5-debug.apk') as response:
                    self.assertEqual(response.read(),b'redesigned-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.0-debug.apk') as response:
                    self.assertEqual(response.read(),b'standalone-mobile-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.1-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-login-ui-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.2-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-login-footer-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.3-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-login-policy-text-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.4-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-page-layout-apk-fixture')
                try:
                    response=urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.5-debug.apk')
                except urllib.error.HTTPError as error:
                    response=error
                with response:
                    self.assertEqual(response.code,200,'new APK must be downloadable')
                    self.assertEqual(response.read(),b'mobile-image-https-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.8-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-alert-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.9-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-recovery-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.15-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-connection-timing-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.16-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-notice-body-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.17-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-source-flow-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.18-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-history-filter-apk-fixture')
                with urllib.request.urlopen(url+'/downloads/courseinbox-learning-0.3.19-debug.apk') as response:
                    self.assertEqual(response.read(),b'mobile-inbox-cleanup-apk-fixture')
                for name,expected in [('courseinbox-learning-0.3.20-debug.apk',b'mobile-arm-apk-fixture'),('courseinbox-learning-0.3.20-arm64-debug.apk',b'mobile-arm64-apk-fixture'),('courseinbox-learning-0.3.20-universal-debug.apk',b'mobile-universal-apk-fixture')]:
                    with urllib.request.urlopen(url+'/downloads/'+name) as response:
                        self.assertEqual(response.read(),expected)
                for path in ['/downloads/private.txt','/downloads/../private.txt','/downloads/access-token.txt']:
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+path)
                    self.assertEqual(error.exception.code,404)
            finally:server.shutdown();server.server_close();thread.join()


class DemoClockTests(unittest.TestCase):
    def test_demo_extension_can_be_confirmed_before_nine_in_morning(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(Path(tmp)/'inbox.sqlite3')
            seed_demo(inbox,current=datetime(2026,10,5,0,5,tzinfo=CN))
            extension=next(p for p in inbox.proposals() if p['action']=='update')
            self.assertEqual(inbox.confirm(extension['id'])['version'],2)
