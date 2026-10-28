"""Restricted LAN reminder listener with independent per-phone receipts."""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import ValidationError, dump, now_iso, parse_timestamp
from .discovery import local_ipv4, private_ipv4, lan_ipv4


class MobileReminders:
    def __init__(self,inbox,alerts,server_id,sync_status,port=8766,listen_host='0.0.0.0'):
        self.inbox,self.alerts,self.server_id,self.sync_status=inbox,alerts,server_id,sync_status
        self.lock=threading.RLock();self.control=threading.Lock();self.server=None;self.thread=None
        self.enabled=False;self.error='';self.port=port;self.listen_host=listen_host
        self.changed=threading.Condition();self.revision=0
        self.unsubscribe=inbox.subscribe_changes(self.wake)
        self.code=None;self.code_expires=None;self.attempts={};self.code_attempts=0
        self.config=inbox.path.parent/'mobile-reminders.json'
        with inbox.lock,inbox.connection(notify=False) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mobile_reminder_devices'").fetchone()
            if not exists and db.execute('SELECT 1 FROM messages LIMIT 1').fetchone():
                directory=inbox.path.parent/'backups';directory.mkdir(exist_ok=True)
                backup=sqlite3.connect(directory/('before-mobile-reminders-'+uuid.uuid4().hex+'.sqlite3'))
                try:db.backup(backup)
                finally:backup.close()
            db.executescript('''
            CREATE TABLE IF NOT EXISTS mobile_reminder_devices(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mobile_reminder_receipts(device_id TEXT NOT NULL,event_id TEXT NOT NULL,issued_at TEXT,acknowledged_at TEXT,PRIMARY KEY(device_id,event_id));
            ''')
        try:config=json.loads(self.config.read_text(encoding='utf-8'))
        except (OSError,ValueError):config={}
        from .web_push import WebPush
        self.push=WebPush(self)
        from .wechat_push import WechatPush
        self.wechat=WechatPush(self)
        if config.get('enabled') is True:self.configure(True)

    @staticmethod
    def digest(token):return hashlib.sha256(token.encode()).hexdigest()

    def status(self):
        with self.lock,self.inbox.connection(notify=False) as db:
            moment=parse_timestamp(now_iso());devices=[]
            for row in db.execute('SELECT id,data FROM mobile_reminder_devices ORDER BY rowid DESC'):
                data=json.loads(row['data']);seen=data.get('last_seen')
                devices.append(dict(id=row['id'],name=data['name'],paired_at=data['paired_at'],last_seen=seen,
                                    web_push=bool(db.execute('SELECT 1 FROM web_push_subscriptions WHERE device_id=?',(row['id'],)).fetchone()),
                                    online=bool(self.enabled and seen and 0<=(moment-parse_timestamp(seen)).total_seconds()<60)))
            try:addresses=sorted(lan_ipv4())
            except OSError:addresses=[]
            port=self.server.server_port if self.server else self.port
            return dict(enabled=self.enabled,listening=self.server is not None,port=port,
                        addresses=['http://'+a+':'+str(port) for a in addresses],server_id=self.server_id,
                        devices=devices,error=self.error,android_version='0.3.21',web_push=self.push.status())

    def configure(self,enabled):
        if type(enabled) is not bool:raise ValidationError('手机提醒开关无效。')
        with self.control:
            if enabled:
                with self.lock:
                    if self.server is None:
                        try:
                            self.server=self._listener();self.enabled=True;self.error=''
                            self.thread=threading.Thread(target=self.server.serve_forever,name='CourseInbox-phone-reminders',daemon=True);self.thread.start()
                        except OSError:
                            self.enabled=False;self.error='提醒端口无法启动，请检查端口是否被占用。'
            else:self._stop()
            with self.lock:
                temporary=self.config.with_suffix('.json.tmp')
                temporary.write_text(dump(dict(enabled=self.enabled)),encoding='utf-8');temporary.replace(self.config)
            self.wake()
            return self.status()

    def _stop(self):
        with self.lock:
            server,thread=self.server,self.thread;self.enabled=False;self.server=None;self.thread=None;self.code=None
        self.wake()
        if server:
            server.shutdown();server.server_close()
            if thread:thread.join(timeout=3)

    def close(self):
        self.wechat.close()
        with self.control:self._stop()
        self.push.close()
        self.unsubscribe()

    def wake(self):
        with self.changed:self.revision+=1;self.changed.notify_all()

    def make_pairing(self,at=None):
        with self.lock:
            if not self.enabled:raise ValidationError('请先开启手机提醒服务。')
            self.code=f'{secrets.randbelow(1000000):06d}';self.code_expires=(parse_timestamp(at or now_iso())+timedelta(minutes=5)).isoformat()
            self.attempts={};self.code_attempts=0
            return dict(code=self.code,expires_at=self.code_expires)

    def _events(self,db,moment,paired_at):
        events=self.alerts._events(db,moment,initialized_at=paired_at)
        for row in db.execute("SELECT p.id,p.data,m.data AS message_data,t.data AS task_data FROM proposals p JOIN messages m ON m.id=p.message_id JOIN tasks t ON t.id=p.task_id WHERE p.status='confirmed' AND m.hidden_at IS NULL"):
            proposal=json.loads(row['data']);message=json.loads(row['message_data']);task=json.loads(row['task_data']);external=message.get('external',{})
            from .checkin_evidence import task_verification
            if task_verification(db,task) in ('unverified','ambiguous','ended'):continue
            if message.get('sample') or task.get('merged_into') or task['status'] in ('submitted','cancelled'):continue
            if not ('学习通' in message.get('source','') or external.get('platform')=='chaoxing-web'):continue
            if proposal.get('action') not in ('create','update','conflict'):continue
            stamp=message.get('received_at') if external.get('time_known') is False else message.get('captured_at')
            if not stamp or parse_timestamp(stamp)<parse_timestamp(paired_at):continue
            candidate=proposal['candidate'];changed=proposal.get('action') in ('update','conflict')
            events.append(dict(id='proposal:'+row['id'],kind='deadline_change' if changed else 'new_pending',
                               title='学习通任务有变更' if changed else '学习通有新任务',body=(candidate.get('course','')+' · '+candidate['title'])[:220],
                               url='/?task='+task['id']+'#tasks',_source_kind=external.get('kind'),_source_at=message.get('captured_at'),_inventory_key=self.alerts._inventory_key(external)))
        associated={row[0] for row in db.execute('SELECT message_id FROM proposals UNION SELECT message_id FROM proposal_sources')}
        for row in db.execute('SELECT id,data FROM messages WHERE hidden_at IS NULL'):
            if row['id'] in associated:continue
            message=json.loads(row['data']);external=message.get('external',{})
            if message.get('sample') or not ('学习通' in message.get('source','') or external.get('platform')=='chaoxing-web'):continue
            if external.get('kind') in ('task_center','checkin_activity'):continue
            stamp=message.get('received_at') if external.get('time_known') is False else message.get('captured_at')
            if not stamp or parse_timestamp(stamp)<parse_timestamp(paired_at):continue
            events.append(dict(id='message:'+message['id'],kind='new_message',title='学习通新消息',
                               body=(external.get('title','')+'\n'+message['text']).strip()[:240],url='/?message='+message['id']+'#inbox'))
        return events

    def pair(self,code,name,at=None,peer='local'):
        moment=parse_timestamp(at or now_iso());status=self.sync_status()
        with self.lock,self.inbox.lock,self.inbox.connection(notify=False) as db:
            if not self.enabled:raise ValidationError('手机提醒服务已关闭。')
            tries=self.attempts.get(peer,0);self.attempts[peer]=tries+1;self.code_attempts+=1
            if len(self.attempts)>256:self.attempts.clear();self.code=None
            if tries>=5 or self.code_attempts>20:raise ValidationError('配对尝试过多，请在电脑重新生成配对码。')
            if not isinstance(code,str) or not re.fullmatch('[0-9]{6}',code) or not self.code or not hmac.compare_digest(code,self.code) or moment>=parse_timestamp(self.code_expires):raise ValidationError('配对码无效或已过期，请在电脑重新生成。')
            if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValidationError('请填写80字以内的设备名称。')
            if db.execute('SELECT COUNT(*) FROM mobile_reminder_devices').fetchone()[0]>=10:raise ValidationError('最多配对10台设备，请先撤销不再使用的设备。')
            token=secrets.token_urlsafe(32);device=uuid.uuid4().hex
            data=dict(name=name.strip(),paired_at=moment.isoformat(),last_seen=None,primed_sections=status.get('sources',{}).get('task_center',{}).get('discovered_sections',[]),inventory_epoch=status.get('inventory_epoch',0))
            db.execute('INSERT INTO mobile_reminder_devices VALUES(?,?,?)',(device,self.digest(token),dump(data)))
            baseline=[event['id'] for event in self._events(db,moment,data['paired_at'])]
            db.executemany('INSERT INTO mobile_reminder_receipts VALUES(?,?,NULL,?)',((device,event,moment.isoformat()) for event in baseline))
            self.code=None
            return dict(token=token,device_id=device,server_id=self.server_id)

    def _device(self,db,token):
        if not self.enabled:raise ValidationError('手机提醒服务已关闭。')
        if not isinstance(token,str) or not 20<=len(token)<=100:raise PermissionError()
        row=db.execute('SELECT id,data FROM mobile_reminder_devices WHERE token_hash=?',(self.digest(token),)).fetchone()
        if not row:raise PermissionError()
        return row['id'],json.loads(row['data'])

    def poll(self,token,at=None,*,_device_id=None):
        moment=parse_timestamp(at or now_iso());status=self.sync_status()
        with self.lock,self.inbox.lock,self.inbox.connection(notify=False) as db:
            if _device_id is None:device,data=self._device(db,token)
            else:
                row=db.execute('SELECT id,data FROM mobile_reminder_devices WHERE id=?',(_device_id,)).fetchone()
                if not self.enabled or not row:raise PermissionError()
                device,data=row['id'],json.loads(row['data'])
            events=self._events(db,moment,data['paired_at']);primed=set(data.get('primed_sections',[]))
            if data.get('inventory_epoch')!=status.get('inventory_epoch',0):primed=set()
            cutoffs=status.get('sources',{}).get('task_center',{}).get('discovered_section_times',{})
            baseline=[];held=set()
            for event in events:
                key=event.get('_inventory_key')
                if event.get('_source_kind')!='task_center' or key in primed:continue
                cutoff=cutoffs.get(key);observed=event.get('_source_at')
                if not cutoff:held.add(event['id']);continue
                if not observed or parse_timestamp(observed)<=parse_timestamp(cutoff):baseline.append(event['id'])
            db.executemany('INSERT OR IGNORE INTO mobile_reminder_receipts VALUES(?,?,NULL,?)',((device,event,moment.isoformat()) for event in baseline))
            completed=set(cutoffs) if status.get('enabled') else set()
            data.update(primed_sections=sorted(primed|completed),inventory_epoch=status.get('inventory_epoch',0))
            if _device_id is None:data['last_seen']=moment.isoformat()
            db.execute('UPDATE mobile_reminder_devices SET data=? WHERE id=?',(dump(data),device))
            acknowledged={row[0] for row in db.execute('SELECT event_id FROM mobile_reminder_receipts WHERE device_id=? AND acknowledged_at IS NOT NULL',(device,))}
            pending=[event for event in events if event['id'] not in acknowledged and event['id'] not in held][:20]
            for event in pending:db.execute('INSERT OR IGNORE INTO mobile_reminder_receipts VALUES(?,?,?,NULL)',(device,event['id'],moment.isoformat()))
            return dict(enabled=True,server_id=self.server_id,events=[{key:value for key,value in event.items() if not key.startswith('_')} for event in pending],poll_after=15)

    def ack(self,token,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9:_.-]{1,200}',value) for value in ids):raise ValidationError('提醒回执无效。')
        with self.lock,self.inbox.lock,self.inbox.connection(notify=False) as db:
            device,_=self._device(db,token)
            for event in ids:
                if not db.execute('SELECT 1 FROM mobile_reminder_receipts WHERE device_id=? AND event_id=? AND issued_at IS NOT NULL',(device,event)).fetchone():raise ValidationError('只能确认已发送给本设备的提醒。')
            db.executemany('UPDATE mobile_reminder_receipts SET acknowledged_at=? WHERE device_id=? AND event_id=?',((now_iso(),device,event) for event in ids))
            return dict(ok=True)

    def revoke(self,device):
        if not isinstance(device,str) or not re.fullmatch('[0-9a-f]{32}',device):raise ValidationError('设备编号无效。')
        with self.lock,self.inbox.lock,self.inbox.connection(notify=False) as db:
            db.execute('DELETE FROM mobile_reminder_devices WHERE id=?',(device,));db.execute('DELETE FROM mobile_reminder_receipts WHERE device_id=?',(device,))
            self.push.remove(db,device)
        self.wake();return dict(ok=True)

    def _listener(self):
        hub=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.0'
            def log_message(self,*args):pass
            def reply(self,status,data):
                raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
            def body(self,maximum=4096):
                try:size=int(self.headers.get('Content-Length','0'))
                except ValueError:raise ValidationError('请求长度无效。') from None
                if not 0<size<=maximum or self.headers.get('Transfer-Encoding') or 'application/json' not in self.headers.get('Content-Type',''):raise ValidationError('请求格式无效。')
                try:data=json.loads(self.rfile.read(size))
                except (ValueError,UnicodeDecodeError):raise ValidationError('请求格式无效。') from None
                if not isinstance(data,dict):raise ValidationError('请求格式无效。')
                return data
            def do_GET(self):self.route('GET')
            def do_POST(self):self.route('POST')
            def stream(self,token):
                batch=hub.poll(token)  # Authenticate before sending streaming headers.
                self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8')
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Connection','close');self.end_headers()
                signature=None
                try:
                    while hub.enabled:
                        with hub.changed:revision=hub.revision
                        batch=hub.poll(token)
                        current=json.dumps(batch['events'],ensure_ascii=False)
                        if current!=signature:
                            self.wfile.write(('data: '+json.dumps(batch,ensure_ascii=False)+'\n\n').encode());signature=current
                        else:self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
                        with hub.changed:hub.changed.wait_for(lambda:hub.revision!=revision or not hub.enabled,timeout=15)
                    self.wfile.write(('data: '+json.dumps(dict(enabled=False,server_id=hub.server_id,events=[]))+'\n\n').encode());self.wfile.flush()
                except PermissionError:
                    self.wfile.write(b'data: {"error":"revoked"}\n\n');self.wfile.flush()
                except (ValidationError,ConnectionError,socket.timeout,OSError):pass
                self.close_connection=True
            def route(self,method):
                try:
                    self.connection.settimeout(8);host=self.headers.get('Host','');target=urlsplit('http://'+host)
                    peersafe=ipaddress.ip_address(self.client_address[0]).is_loopback or private_ipv4(self.client_address[0])
                    allowed={'127.0.0.1','localhost',*(address for address in local_ipv4() if private_ipv4(address))}
                    from .web_push import public_origin
                    origin=public_origin(hub.inbox.path.parent)
                    proxied=bool(origin and ipaddress.ip_address(self.client_address[0]).is_loopback and 'https://'+host==origin)
                    if not proxied and (not peersafe or target.hostname not in allowed or target.port!=self.server.server_port or target.path or target.username or target.password):return self.reply(403,dict(error='只允许本机、局域网或已配置的 HTTPS 入口连接。'))
                    if self.headers.get('Origin') not in (None,origin if proxied else 'http://'+host):return self.reply(403,dict(error='请求来源未授权。'))
                    path=urlsplit(self.path).path
                    phone_assets={'/':('index.html','text/html'),'/phone.js':('phone.js','text/javascript'),'/phone.css':('phone.css','text/css'),'/sw.js':('sw.js','text/javascript'),'/push.js':('push.js','text/javascript'),'/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),'/icon.svg':('icon.svg','image/svg+xml')}
                    if method=='GET' and path in phone_assets:
                        filename,content_type=phone_assets[path]
                        raw=(Path(__file__).resolve().parents[1]/'web'/'phone-reminders'/filename).read_bytes()
                        self.send_response(200);self.send_header('Content-Type',content_type+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
                        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer')
                        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; worker-src 'self'; manifest-src 'self'; img-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
                        self.end_headers();self.wfile.write(raw);return
                    if method=='GET' and path=='/v1/health':return self.reply(200,dict(app='CourseInbox Reminders',version=1,server_id=hub.server_id))
                    filename=path.removeprefix('/downloads/')
                    if method=='GET' and path.startswith('/downloads/') and filename in ('courseinbox-learning-0.3.21-debug.apk','courseinbox-learning-0.3.21-arm64-debug.apk'):
                        apk=Path(__file__).resolve().parents[1]/'artifacts'/'mobile'/filename
                        if not apk.is_file():return self.reply(404,dict(error='安装包尚未构建。'))
                        with apk.open('rb') as stream:
                            self.send_response(200);self.send_header('Content-Type','application/vnd.android.package-archive')
                            self.send_header('Content-Length',str(os.fstat(stream.fileno()).st_size));self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
                            self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                            while chunk:=stream.read(128*1024):self.wfile.write(chunk)
                        return
                    if method=='POST' and path=='/v1/pair':
                        body=self.body()
                        if set(body)!={'code','name'}:raise ValidationError('配对参数无效。')
                        return self.reply(200,hub.pair(body['code'],body['name'],peer=self.client_address[0]))
                    if path not in ('/v1/alerts','/v1/ack','/v1/stream','/v1/push/key','/v1/push/subscribe','/v1/push/unsubscribe'):return self.reply(404,dict(error='接口不存在。'))
                    auth=self.headers.get('Authorization','');token=auth[7:] if auth.startswith('Bearer ') else ''
                    if path=='/v1/push/key' and method=='GET':
                        with hub.lock,hub.inbox.connection(notify=False) as db:hub._device(db,token)
                        return self.reply(200,dict(public_key=hub.push.keys()[1]))
                    if path=='/v1/push/subscribe' and method=='POST':return self.reply(200,hub.push.subscribe(token,self.body(8192)))
                    if path=='/v1/push/unsubscribe' and method=='POST':return self.reply(200,hub.push.unsubscribe(token))
                    if method=='GET' and path=='/v1/stream':return self.stream(token)
                    if method=='GET' and path=='/v1/alerts':return self.reply(200,hub.poll(token))
                    if method=='POST' and path=='/v1/ack':
                        body=self.body(32768)
                        if set(body)!={'ids'}:raise ValidationError('提醒回执无效。')
                        return self.reply(200,hub.ack(token,body['ids']))
                    return self.reply(405,dict(error='方法不支持。'))
                except PermissionError:self.reply(401,dict(error='设备未配对或已撤销，请重新配对。'))
                except ValidationError as error:self.reply(400,dict(error=str(error)))
                except (ConnectionError,socket.timeout):pass
                except Exception:self.reply(500,dict(error='提醒服务暂不可用。'))
        class Server(ThreadingHTTPServer):
            daemon_threads=True
            allow_reuse_address=os.name!='nt'
            slots=threading.BoundedSemaphore(32)
            def get_request(self):
                connection,address=super().get_request();connection.settimeout(8)
                return connection,address
            def process_request(self,request,address):
                if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
                try:super().process_request(request,address)
                except BaseException:self.slots.release();raise
            def process_request_thread(self,request,address):
                try:super().process_request_thread(request,address)
                finally:self.slots.release()
            def server_bind(self):
                if os.name=='nt' and hasattr(socket,'SO_EXCLUSIVEADDRUSE'):self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                super().server_bind()
        return Server((self.listen_host,self.port),Handler)
