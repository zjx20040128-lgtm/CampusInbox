"""pushplus WeChat summaries, independent of LAN pairing and browser push."""
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from .core import ValidationError,dump,now_iso,parse_timestamp
from .session_crypto import seal,unseal


class WechatPush:
    def __init__(self,hub):
        self.hub=hub;self.inbox=hub.inbox;self.lock=threading.RLock();self.closed=False
        self.secret=self.inbox.path.parent/'wechat-push-token.bin'
        with self.inbox.connection(notify=False) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS wechat_push_settings(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wechat_push_events(id TEXT PRIMARY KEY,data TEXT NOT NULL);''')
            for row in db.execute('SELECT id,data FROM wechat_push_events').fetchall():
                value=json.loads(row['data'])
                if value['state']=='sending':
                    value.update(state='unknown',error='上次发送期间服务中断，结果不明；未自动重发。')
                    db.execute('UPDATE wechat_push_events SET data=? WHERE id=?',(dump(value),row['id']))
        self.thread=threading.Thread(target=self.run,name='CampusInbox-WeChat',daemon=True);self.thread.start()

    @staticmethod
    def _config(db):
        row=db.execute('SELECT data FROM wechat_push_settings WHERE id=1').fetchone()
        return json.loads(row[0]) if row else dict(enabled=False)

    @staticmethod
    def _save(db,config):db.execute('INSERT OR REPLACE INTO wechat_push_settings VALUES(1,?)',(dump(config),))

    def _token(self):
        try:return unseal(self.secret.read_bytes()).decode()
        except Exception:raise ValidationError('Token 未配置或本机无法解密，请重新填写。') from None

    def status(self):
        with self.inbox.connection(notify=False) as db:
            config=self._config(db)
            recent=[json.loads(r[0]) for r in db.execute('SELECT data FROM wechat_push_events ORDER BY rowid DESC LIMIT 30')]
        recent=[r for r in recent if r['state']!='baseline'][:5]
        last=recent[0] if recent else {}
        return dict(enabled=config.get('enabled',False),paused=config.get('blocked',False),configured=self.secret.is_file(),provider='pushplus',
                    last_result=last.get('state','none'),last_at=last.get('at'),last_error=last.get('error',''),
                    receipt=last.get('receipt',''),recent=recent)

    def _events(self,db,config):
        moment=parse_timestamp(now_iso());anchor=config.get('enabled_at',moment.isoformat())
        # Existing events are baselined on enable; include the rest of the current
        # publication minute so new notices with minute precision are not lost.
        anchor=(parse_timestamp(anchor)-timedelta(seconds=60)).isoformat()
        events=self.hub._events(db,moment,anchor)
        status=self.hub.sync_status();source=status.get('sources',{}).get('task_center',{})
        primed=set(config.get('primed_sections',[])) if config.get('inventory_epoch')==status.get('inventory_epoch',0) else set()
        cutoffs=source.get('discovered_section_times',{})
        result=[]
        for event in events:
            key=event.get('_inventory_key')
            if event.get('_source_kind')=='task_center' and key not in primed:
                cutoff=cutoffs.get(key);observed=event.get('_source_at')
                if not cutoff or not observed or parse_timestamp(observed)<=parse_timestamp(cutoff):continue
            event=dict(event)
            if event.get('kind')=='new_message':event['body']='学习通有新消息，请在电脑消息收件箱查看。'
            elif event['id'].startswith('proposal:'):
                row=db.execute('SELECT data,task_id,status FROM proposals WHERE id=?',(event['id'].split(':',1)[1],)).fetchone()
                if row:
                    proposal=json.loads(row['data']);deadline=proposal.get('candidate',{}).get('deadline')
                    if row['status']=='confirmed' and row['task_id']:
                        task=db.execute('SELECT data FROM tasks WHERE id=?',(row['task_id'],)).fetchone()
                        if task:deadline=json.loads(task[0]).get('deadline')
                    event['body']+='\n截止：'+(deadline.replace('T',' ').removesuffix('+08:00') if deadline else '未明确')
            result.append(event)
        return result

    def configure(self,body):
        if not isinstance(body,dict) or set(body)-{'enabled','token','clear_token'} or type(body.get('enabled')) is not bool:raise ValidationError('微信推送设置无效。')
        if 'clear_token' in body and type(body['clear_token']) is not bool:raise ValidationError('清除 Token 参数无效。')
        if body.get('clear_token') and ('token' in body or body['enabled']):raise ValidationError('清除 Token 时不能同时开启或替换 Token。')
        with self.lock,self.inbox.lock,self.inbox.connection(notify=False) as db:
            previous=self._config(db);config=dict(previous)
            if body.get('clear_token'):
                if body['enabled']:raise ValidationError('请先关闭微信推送再清除 Token。')
                self.secret.unlink(missing_ok=True);config=dict(enabled=False)
            token=body.get('token')
            if token is not None:
                if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,256}',token):raise ValidationError('Token 格式无效，请填写 pushplus 用户或消息 Token。')
                account=hashlib.sha256(token.encode()).hexdigest()[:24]
                temporary=self.secret.with_suffix('.tmp');temporary.write_bytes(seal(token.encode()));temporary.replace(self.secret)
                if config.get('account')!=account:config['next_send']=0
                config['account']=account
            if body['enabled']:
                self._token()
                if not config.get('account'):raise ValidationError('请先保存 Token。')
                if not previous.get('enabled') or previous.get('blocked') or config.get('account')!=previous.get('account'):
                    source=self.hub.sync_status()
                    config.update(enabled_at=now_iso(),inventory_epoch=source.get('inventory_epoch',0),primed_sections=source.get('sources',{}).get('task_center',{}).get('discovered_sections',[]))
                    for event in self._events(db,config):
                        key=config['account']+':'+event['id']
                        db.execute('INSERT OR IGNORE INTO wechat_push_events VALUES(?,?)',(key,dump(dict(state='baseline',at=now_iso()))))
            config['enabled']=body['enabled'];config['blocked']=False;self._save(db,config)
        self.hub.wake();return self.status()

    @staticmethod
    def transport(payload):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        request=urllib.request.Request('https://www.pushplus.plus/send',data=dump(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.build_opener(NoRedirect()).open(request,timeout=8) as response:
                raw=response.read(32769)
                if len(raw)>32768:raise ValueError('response too large')
                result=json.loads(raw)
                if not isinstance(result,dict):raise ValueError('invalid response')
                return result
        except urllib.error.HTTPError as error:
            if error.code==429:return dict(code=429)
            raise

    def _deliver(self,db,config,key,event,attempts):
        account=config['account']
        if hashlib.sha256(self._token().encode()).hexdigest()[:24]!=account:raise ValidationError('Token 与配置不一致，请重新保存。')
        record=dict(state='sending',at=now_iso(),title=event['title'][:120],attempts=attempts)
        # Persist before sending: an interrupted/ambiguous attempt must not cause
        # blind duplicate sends after restart.
        db.execute('INSERT OR REPLACE INTO wechat_push_events VALUES(?,?)',(key,dump(record)));db.commit()
        payload=dict(token=self._token(),title=event['title'][:120],content=event['body'][:500],template='txt',channel='wechat')
        try:
            result=self.transport(payload);code=result.get('code');receipt=result.get('data')
            if code==200 and isinstance(receipt,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',receipt):record.update(state='accepted',receipt=receipt,error='')
            elif code==429 or isinstance(code,int) and 500<=code<600:
                record.update(state='retry' if attempts<3 else 'failed',retry_at=time.time()+120*attempts,error='服务限流或暂时异常，将限次重试。' if attempts<3 else '多次尝试失败，请检查服务额度后再测试。')
            elif code==200:record.update(state='unknown',error='服务响应缺少流水号，结果不明；未自动重发，避免重复。')
            else:record.update(state='failed',error='推送服务拒绝请求，请在 pushplus 检查 Token、微信绑定和额度。')
        except Exception:record.update(state='unknown',error='网络或服务响应异常，结果不明；未自动重发，避免重复。')
        record['at']=now_iso()
        db.execute('UPDATE wechat_push_events SET data=? WHERE id=?',(dump(record),key))
        if record['state'] in ('failed','unknown'):config['blocked']=True
        if record['state']=='retry':config['next_send']=record['retry_at']
        self._save(db,config)

    def dispatch(self):
        if not self.lock.acquire(blocking=False):return
        try:
            with self.inbox.connection(notify=False) as db:
                config=self._config(db)
                if not config.get('enabled') or config.get('blocked') or time.time()<config.get('next_send',0):return
                for event in self._events(db,config):
                    key=config['account']+':'+event['id'];row=db.execute('SELECT data FROM wechat_push_events WHERE id=?',(key,)).fetchone()
                    old=json.loads(row[0]) if row else {}
                    if old and (old['state']!='retry' or old.get('retry_at',0)>time.time()):continue
                    config['next_send']=time.time()+5;self._save(db,config)
                    self._deliver(db,config,key,event,old.get('attempts',0)+1)
                    break
        finally:self.lock.release()

    def test(self):
        with self.lock,self.inbox.connection(notify=False) as db:
            config=self._config(db)
            if not config.get('enabled'):raise ValidationError('请先保存 Token 并开启微信推送。')
            if time.time()<config.get('next_send',0):raise ValidationError('发送间隔至少 5 秒，请稍后再试。')
            config['next_send']=time.time()+5;self._save(db,config)
            self._deliver(db,config,config['account']+':test:'+uuid.uuid4().hex,dict(title='CampusInbox 微信推送测试',body='这是一条测试提醒。收到后，电脑可通过此渠道发送新通知、任务变更和截止提醒。'),1)
        return self.status()

    def run(self):
        while not self.closed:
            with self.hub.changed:revision=self.hub.revision
            try:self.dispatch()
            except Exception:pass
            with self.hub.changed:self.hub.changed.wait_for(lambda:self.closed or self.hub.revision!=revision,timeout=5)

    def close(self):
        self.closed=True;self.hub.wake();self.thread.join(timeout=10)
