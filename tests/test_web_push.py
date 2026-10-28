import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox,now_iso,ValidationError
from courseinbox.desktop_alerts import DesktopAlerts
from courseinbox.mobile_reminders import MobileReminders


class WebPushTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'db.sqlite3')
        self.hub=MobileReminders(self.box,DesktopAlerts(self.box),'a'*32,lambda:{'enabled':False},port=0,listen_host='127.0.0.1')
        self.hub.push.close()  # Deterministic dispatcher; never contact a real provider.
        self.hub.configure(True);self.addCleanup(self.hub.close)
        self.session=self.hub.pair(self.hub.make_pairing()['code'],'后台网页')

    def subscription(self,endpoint='https://fcm.googleapis.com/fcm/send/test'):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        import base64
        encode=lambda data:base64.urlsafe_b64encode(data).decode().rstrip('=')
        key=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        return dict(endpoint=endpoint,keys=dict(p256dh=encode(key),auth=encode(b'a'*16)))

    def test_subscription_auth_endpoint_validation_and_no_page_delivery(self):
        with self.assertRaises(PermissionError):self.hub.push.subscribe('wrong-token',self.subscription())
        for endpoint in ('http://fcm.googleapis.com/x','https://127.0.0.1/x','https://evil.example/x','https://fcm.googleapis.com:8443/x'):
            with self.assertRaises(ValidationError):self.hub.push.subscribe(self.session['token'],self.subscription(endpoint))
        self.hub.push.subscribe(self.session['token'],self.subscription())
        with patch.object(self.hub.push,'send',return_value=201) as send:
            self.box.ingest('后台通知测试：网页没有打开。',source='学习通课程通知',captured_at=now_iso())
            self.hub.push.dispatch();self.hub.push.dispatch()
            self.assertEqual(send.call_count,1)
        self.hub.revoke(self.session['device_id'])
        self.assertEqual(self.hub.push.status()['subscriptions'],0)

    def test_expired_subscription_removed_and_no_false_phone_ack(self):
        self.hub.push.subscribe(self.session['token'],self.subscription())
        self.box.ingest('失效订阅测试',source='学习通课程通知',captured_at=now_iso())
        with patch.object(self.hub.push,'send',return_value=410):self.hub.push.dispatch()
        self.assertEqual(self.hub.push.status()['subscriptions'],0)
        self.assertTrue(self.hub.poll(self.session['token'])['events'])

    def test_real_encryption_and_vapid_use_bounded_nonredirecting_http(self):
        import requests
        response=requests.Response();response.status_code=201
        with patch.object(requests.Session,'request',return_value=response) as request:
            self.assertEqual(self.hub.push.send(self.subscription(),dict(id='event-1',title='标题',body='正文')),201)
            args=request.call_args.kwargs
            self.assertEqual(args['timeout'],8)
            self.assertFalse(args['allow_redirects'])
            self.assertEqual(args['headers']['content-encoding'],'aes128gcm')
            self.assertNotIn('正文'.encode(),args['data'])

    def test_public_https_proxy_is_scoped_and_key_stays_encrypted(self):
        import http.client
        import json
        origin='https://phone.example.test'
        (self.box.path.parent/'phone-public-origin.json').write_text(json.dumps({'origin':origin}),encoding='utf-8')
        client=http.client.HTTPConnection('127.0.0.1',self.hub.server.server_port,timeout=3);self.addCleanup(client.close)
        client.request('GET','/v1/health',headers={'Host':'evil.example.test'})
        self.assertEqual(client.getresponse().status,403)
        client.close();client.connect()
        client.request('GET','/v1/push/key',headers={'Host':'phone.example.test'})
        self.assertEqual(client.getresponse().status,401)
        client.close();client.connect()
        client.request('GET','/api/state',headers={'Host':'phone.example.test'})
        self.assertEqual(client.getresponse().status,404)
        self.assertEqual(self.hub.push.keys(),self.hub.push.keys())
        self.assertNotIn(b'BEGIN PRIVATE KEY',(self.box.path.parent/'web-push-key.bin').read_bytes())

    def test_commit_wakes_background_sender_without_phone_requests(self):
        import threading,time
        self.hub.push.subscribe(self.session['token'],self.subscription())
        with patch.object(self.hub.push,'send',return_value=201) as send:
            self.hub.push.closed=False
            self.hub.push.thread=threading.Thread(target=self.hub.push.run,daemon=True);self.hub.push.thread.start()
            try:
                self.box.ingest('无页面连接的后台发送',source='学习通课程通知',captured_at=now_iso())
                until=time.monotonic()+3
                while not send.called and time.monotonic()<until:time.sleep(.03)
                self.assertTrue(send.called)
            finally:self.hub.push.close()
