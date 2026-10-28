"""Optional standards-based Web Push; browser acceptance is not a phone receipt."""
import base64
import json
import threading
import time
from urllib.parse import urlsplit
from .core import ValidationError,dump,now_iso


def public_origin(directory):
    try:
        value=json.loads((directory/'phone-public-origin.json').read_text(encoding='utf-8-sig'))['origin']
        u=urlsplit(value)
        if u.scheme=='https' and u.hostname and not u.username and not u.password and u.port in (None,443) and not u.query and not u.fragment and u.path in ('','/'):
            return 'https://'+u.netloc
    except (OSError,ValueError,KeyError,TypeError):pass
    return ''


class WebPush:
    def __init__(self,hub):
        self.hub=hub;self.closed=False;self.delivery_lock=threading.Lock();self.key_lock=threading.Lock()
        with hub.inbox.connection(notify=False) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS web_push_subscriptions(device_id TEXT PRIMARY KEY,data TEXT NOT NULL,retry_at REAL NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS web_push_sent(device_id TEXT,event_id TEXT,sent_at TEXT,PRIMARY KEY(device_id,event_id));''')
        self.thread=threading.Thread(target=self.run,name='CampusInbox-WebPush',daemon=True);self.thread.start()

    def keys(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from .session_crypto import seal,unseal
        with self.key_lock:
            path=self.hub.inbox.path.parent/'web-push-key.bin'
            if path.exists():pem=unseal(path.read_bytes())
            else:
                key=ec.generate_private_key(ec.SECP256R1())
                pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
                temporary=path.with_suffix('.tmp');temporary.write_bytes(seal(pem));temporary.replace(path)
            key=serialization.load_pem_private_key(pem,password=None)
            raw=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
            return pem.decode(),base64.urlsafe_b64encode(raw).decode().rstrip('=')

    def status(self):
        try:import pywebpush;available=True
        except ImportError:available=False
        with self.hub.inbox.connection(notify=False) as db:
            count=db.execute('SELECT COUNT(*) FROM web_push_subscriptions s JOIN mobile_reminder_devices d ON d.id=s.device_id').fetchone()[0]
        return dict(available=available,subscriptions=count,origin=public_origin(self.hub.inbox.path.parent))

    def subscribe(self,token,subscription):
        with self.hub.lock,self.hub.inbox.connection(notify=False) as db:
            device,_=self.hub._device(db,token)
            if not isinstance(subscription,dict) or set(subscription)-{'endpoint','keys','expirationTime'}:raise ValidationError('推送订阅格式无效。')
            endpoint=subscription.get('endpoint','');keys=subscription.get('keys',{})
            try:
                u=urlsplit(endpoint)
                hosts=('fcm.googleapis.com','fcm.push.google.com','updates.push.services.mozilla.com','web.push.apple.com')
                allowed=u.hostname in hosts or bool(u.hostname and u.hostname.endswith('.notify.windows.com'))
                if len(endpoint)>4096 or not allowed or u.scheme!='https' or u.port not in (None,443) or u.username or u.password or u.fragment:raise ValueError()
                if not isinstance(keys,dict) or set(keys)!={'auth','p256dh'}:raise ValueError()
                from cryptography.hazmat.primitives.asymmetric import ec
                def decode(v):
                    if not isinstance(v,str) or len(v)>200:raise ValueError()
                    return base64.b64decode(v+'='*(-len(v)%4),altchars=b'-_',validate=True)
                if len(decode(keys['auth']))!=16:raise ValueError()
                ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),decode(keys['p256dh']))
            except (ValueError,TypeError,KeyError):raise ValidationError('推送服务地址或加密密钥无效。') from None
            db.execute('INSERT OR REPLACE INTO web_push_subscriptions(device_id,data) VALUES(?,?)',(device,dump(dict(endpoint=endpoint,keys=keys))))
        self.hub.wake();return dict(ok=True)

    def unsubscribe(self,token):
        with self.hub.lock,self.hub.inbox.connection(notify=False) as db:
            device,_=self.hub._device(db,token);self.remove(db,device)
        return dict(ok=True)

    @staticmethod
    def remove(db,device):
        db.execute('DELETE FROM web_push_subscriptions WHERE device_id=?',(device,))
        db.execute('DELETE FROM web_push_sent WHERE device_id=?',(device,))

    def send(self,subscription,event):
        import requests
        from pywebpush import webpush,WebPushException
        from py_vapid import Vapid
        pem,_=self.keys()
        class NoRedirect(requests.Session):
            def request(self,*args,**kwargs):kwargs['allow_redirects']=False;return super().request(*args,**kwargs)
        payload=dict(id=event['id'],title=event['title'][:120],body=event['body'][:400])
        with NoRedirect() as session:
            try:
                response=webpush(subscription_info=subscription,data=dump(payload),vapid_private_key=Vapid.from_pem(pem.encode()),
                    vapid_claims={'sub':public_origin(self.hub.inbox.path.parent) or 'https://campusinbox.invalid'},
                    ttl=3600,timeout=8,requests_session=session)
                return response.status_code
            except WebPushException as error:
                return error.response.status_code if error.response is not None else 503

    def dispatch(self):
        if not self.hub.enabled or not self.delivery_lock.acquire(blocking=False):return
        try:
            with self.hub.inbox.connection(notify=False) as db:
                subscriptions=list(db.execute('SELECT s.device_id,s.data FROM web_push_subscriptions s JOIN mobile_reminder_devices d ON d.id=s.device_id WHERE retry_at<=?',(time.time(),)))
            for row in subscriptions:
                try:batch=self.hub.poll(None,_device_id=row['device_id'])
                except (PermissionError,ValidationError):continue
                for event in batch['events']:
                    if not self.hub.enabled:return
                    with self.hub.inbox.connection(notify=False) as db:
                        if not db.execute('SELECT 1 FROM web_push_subscriptions s JOIN mobile_reminder_devices d ON d.id=s.device_id WHERE s.device_id=?',(row['device_id'],)).fetchone():break
                        if db.execute('SELECT 1 FROM web_push_sent WHERE device_id=? AND event_id=?',(row['device_id'],event['id'])).fetchone():continue
                    try:code=self.send(json.loads(row['data']),event)
                    except Exception:code=503
                    with self.hub.inbox.connection(notify=False) as db:
                        if 200<=code<300:
                            db.execute('INSERT OR IGNORE INTO web_push_sent VALUES(?,?,?)',(row['device_id'],event['id'],now_iso()))
                            db.execute("UPDATE web_push_subscriptions SET last_error='',retry_at=0 WHERE device_id=?",(row['device_id'],))
                        elif code in (404,410):self.remove(db,row['device_id'])
                        else:db.execute('UPDATE web_push_subscriptions SET retry_at=?,last_error=? WHERE device_id=?',(time.time()+60,'推送服务暂不可达，将自动重试。',row['device_id']))
                    if not 200<=code<300:break
        finally:self.delivery_lock.release()

    def run(self):
        while not self.closed:
            with self.hub.changed:revision=self.hub.revision
            try:self.dispatch()
            except Exception:pass
            with self.hub.changed:self.hub.changed.wait_for(lambda:self.closed or self.hub.revision!=revision,timeout=15)

    def close(self):
        self.closed=True;self.hub.wake();self.thread.join(timeout=10)
