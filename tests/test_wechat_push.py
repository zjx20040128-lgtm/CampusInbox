import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox,ValidationError,now_iso
from courseinbox.desktop_alerts import DesktopAlerts
from courseinbox.mobile_reminders import MobileReminders


class WechatPushTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'db.sqlite3')
        self.hub=MobileReminders(self.box,DesktopAlerts(self.box),'a'*32,lambda:{'enabled':False},port=0,listen_host='127.0.0.1')
        self.addCleanup(self.hub.close)
        self.sender=self.hub.wechat
        self.sender.close()  # Manual dispatch, no real recipient or network.
        self.token='test-private-token-never-send-1234'

    def enable(self):return self.sender.configure({'enabled':True,'token':self.token})

    def test_secret_is_encrypted_and_not_returned_and_enable_needs_token(self):
        with self.assertRaises(ValidationError):self.sender.configure({'enabled':True})
        state=self.enable();self.assertTrue(state['configured']);self.assertNotIn(self.token,json.dumps(state))
        self.assertNotIn(self.token.encode(),self.sender.secret.read_bytes())
        self.assertEqual(self.sender._token(),self.token)

    def test_old_messages_baselined_and_new_message_sent_once_independent_of_phone(self):
        self.box.ingest('启用前的旧通知',source='学习通课程通知',captured_at=now_iso())
        self.enable()
        with patch.object(self.sender,'transport',return_value={'code':200,'data':'receipt-123'}) as send:
            self.sender.dispatch();self.assertEqual(send.call_count,0)
            self.box.ingest('启用后的新通知',source='学习通课程通知',captured_at=now_iso())
            self.sender.dispatch();self.sender.dispatch();self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0]['channel'],'wechat')
            self.assertEqual(self.sender.status()['last_result'],'accepted')
        self.assertFalse(self.hub.enabled)

    def test_rejected_token_and_ambiguous_timeout_are_not_retried_as_new_messages(self):
        self.enable();self.box.ingest('需要通知的消息',source='学习通课程通知',captured_at=now_iso())
        with patch.object(self.sender,'transport',side_effect=TimeoutError('secret '+self.token)) as send:
            self.sender.dispatch();self.sender.dispatch();self.assertEqual(send.call_count,1)
        state=self.sender.status();self.assertEqual(state['last_result'],'unknown');self.assertNotIn(self.token,json.dumps(state))

    def test_disable_clear_and_test_notification(self):
        self.enable()
        with patch.object(self.sender,'transport',return_value={'code':200,'data':'test-receipt'}):
            result=self.sender.test();self.assertEqual(result['last_result'],'accepted')
        self.sender.configure({'enabled':False,'clear_token':True})
        self.assertFalse(self.sender.status()['configured']);self.assertFalse(self.sender.secret.exists())

    def test_rate_limit_backoff_is_bounded_and_failure_pauses_automatic_sends(self):
        import time
        start=time.time();self.enable();self.box.ingest('限流测试通知',source='学习通课程通知',captured_at=now_iso())
        with patch.object(self.sender,'transport',return_value={'code':429}) as send:
            self.sender.dispatch();self.assertEqual(self.sender.status()['last_result'],'retry')
            self.sender.dispatch();self.assertEqual(send.call_count,1)
            with patch('courseinbox.wechat_push.time.time',return_value=start+130):self.sender.dispatch()
            with patch('courseinbox.wechat_push.time.time',return_value=start+400):self.sender.dispatch()
            self.assertEqual(send.call_count,3)
            self.assertEqual(self.sender.status()['last_result'],'failed');self.assertTrue(self.sender.status()['paused'])

    def test_sender_uses_https_json_and_does_not_send_raw_chat_body(self):
        import io
        payload={'token':self.token,'title':'测试','content':'摘要','channel':'wechat','template':'txt'}
        with patch('urllib.request.OpenerDirector.open',return_value=io.BytesIO(b'{"code":200,"data":"receipt"}')) as request:
            self.assertEqual(self.sender.transport(payload)['code'],200)
            self.assertEqual(request.call_args.args[0].full_url,'https://www.pushplus.plus/send')
            self.assertNotIn(self.token,request.call_args.args[0].full_url)
            self.assertEqual(request.call_args.kwargs['timeout'],8)
        self.enable();self.box.ingest('不应外发的聊天原文',source='学习通课程通知',captured_at=now_iso())
        with patch.object(self.sender,'transport',return_value={'code':200,'data':'receipt'}) as request:
            self.sender.dispatch();self.assertNotIn('不应外发的聊天原文',request.call_args.args[0]['content'])

    def test_http_settings_and_test_require_main_auth_and_preserve_secret(self):
        import threading,urllib.request,urllib.error
        from courseinbox.http import create_server
        server=create_server('127.0.0.1',0,self.box,'main-auth-test',reminder_port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+'/api/wechat-push/status')
            self.assertEqual(error.exception.code,401)
            def post(path,body):
                request=urllib.request.Request(url+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer main-auth-test','Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=3) as response:return json.load(response)
            status=post('/api/wechat-push/settings',{'enabled':True,'token':self.token})
            self.assertNotIn(self.token,json.dumps(status))
            with patch.object(server.mobile_reminders.wechat,'transport',return_value={'code':200,'data':'api-receipt'}):
                result=post('/api/wechat-push/test',{})
                self.assertEqual(result['last_result'],'accepted');self.assertEqual(result['receipt'],'api-receipt')
        finally:server.shutdown();server.server_close();thread.join(timeout=3)
