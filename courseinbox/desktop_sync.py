"""Dedicated QR sign-in and background messages; never reads another browser."""
import base64,json,os,re,shutil,subprocess,threading,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .core import ValidationError,now_iso
from .chaoxing import ingest_web_message
from .files import extract_file,MAX_UPLOAD
from .session_crypto import seal,unseal
from .task_inventory import TaskInventory

STATES={'idle','connecting','waiting_scan','connected','syncing','expired','paused','error','retrying','partial'}
ERRORS={'coverage':'部分详情、附件或图片尚未读取，请打开原文核对；已支持的内容会继续检查。','network':'网络暂时中断，后台正在重试，无需重新扫码。','expired':'登录已失效，请重新扫码。','dom':'课程通知入口暂未加载，后台会重试；持续失败可打开首次登录窗口核对。','notice':'部分通知暂未读取，已收到的消息已保留，后台会重试。','chat':'部分聊天消息暂未读取，已收到的消息已保留，后台会重试。','task_center':'部分作业或考试列表暂未读取，后台会重试。','attachment':'部分附件或图片尚未完整读取，请打开原文核对；可重试的读取失败会在后台补收。','runtime':'缺少 Node.js / Playwright 或 Edge，请查看桌面同步安装说明。','queue':'待传通知已保留，电脑恢复连接后重试。','session':'本机登录状态无法读取，请重新扫码。','worker':'采集进程已中断，正在复用本机登录状态恢复；已收到的消息已保留。','stalled':'采集进度长时间没有更新，正在恢复；可点立即补收重新检查。'}

STAGES={'portal_navigation','login_ready','list_navigation','list_ready','detail_navigation','detail_content','detail_data','detail_parse','session_save','browser','session','runtime','worker','chat_navigation','chat_ready','chat_conversation','chat_content','task_navigation','task_list'}
REASONS={'timeout','network','interrupted','closed','http_429','http_5xx','http_error','dom','expired','unexpected','session','runtime','worker_exit','stalled'}
COVERAGE={'unknown','loaded_text','partial','list_only','complete'}
HEARTBEAT_TIMEOUT=90
PROGRESS_TIMEOUT=300
MAX_RESTARTS=5

def atomic(path,raw):
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_bytes(raw);temporary.replace(path)

def section_keys(value):
    if not isinstance(value,list):return []
    return list(dict.fromkeys(key for key in value[:1000] if isinstance(key,str) and re.fullmatch(r'[0-9a-f]{24}',key)))[-200:]

def section_times(value,keys):
    if not isinstance(value,dict):return {}
    result={}
    for key in keys:
        stamp=value.get(key)
        if not isinstance(stamp,str) or len(stamp)>40:continue
        try:
            parsed=datetime.fromisoformat(stamp)
            if parsed.tzinfo is not None:result[key]=stamp
        except ValueError:pass
    return result

class DesktopSync:
    def __init__(self,inbox,root,autostart=True):
        self.inbox,self.root=inbox,Path(root);self.directory=inbox.path.parent/'chaoxing-sync';self.directory.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.control=threading.Lock();self.process=None;self.reader=None;self.closed=False;self.epoch=0
        self.wake=threading.Event();self.heartbeat_tick=None;self.last_heartbeat=None;self.restart_at=None;self.next_retry_at=None;self.restart_count=0;self.restart_attempts=0;self.queue_retry_tick=0;self.source_ticks={};self.source_started={}
        config=self._load('config.json',{});self.enabled=config.get('enabled') is True;self.state='connecting' if self.enabled else ('idle' if config.get('logged_out') is True else 'paused' if config else 'idle')
        inventory_epoch=config.get('inventory_epoch',0);self.inventory_epoch=inventory_epoch if type(inventory_epoch) is int and inventory_epoch>=0 else 0
        self.last_checked=config.get('last_checked');self.last_received=config.get('last_received');self.last_error='';self.qr_ready=False;self.last_count=0;self.error_stage='';self.error_code='';self.retry_in=0
        old_source_success=config.get('source_success',{});source_checked=config.get('source_checked',{});source_complete=config.get('source_complete_success',{});source_discovery=config.get('source_discovery_complete',{});source_sections=config.get('source_discovered_sections',{})
        if not isinstance(source_sections,dict):source_sections={}
        source_times=config.get('source_section_times',{})
        if not isinstance(source_times,dict):source_times={}
        self.sources={name:dict(state='connecting' if self.enabled else 'idle',last_checked=source_checked.get(name) or old_source_success.get(name),last_success=source_complete.get(name),discovery_complete=source_discovery.get(name) is True,discovered_sections=section_keys(source_sections.get(name)),last_progress=None,coverage='unknown',checked_count=0,captured_count=0,failed_count=0,pending_count=0,detail_pending_count=0,unsupported_detail_count=0,media_pending_count=0,error='',stage='',reason='',issue_summary='') for name in ('chat','notice','task_center')}
        for name,value in self.sources.items():value['discovered_section_times']=section_times(source_times.get(name),value['discovered_sections'])
        self.pending=self._load('pending.json',[]);self.incomplete=set(self._load('incomplete.json',[]));self.accepted=set(self._load('accepted.json',[]))
        self.inventory=TaskInventory(inbox,self._load('task-inventory.json',{}))
        if autostart:
            threading.Thread(target=self._watch,daemon=True).start()
            if self.enabled:threading.Thread(target=self.start,daemon=True).start()
    def _load(self,name,default):
        try:return json.loads((self.directory/name).read_text(encoding='utf-8'))
        except (OSError,ValueError):return default
    def _save(self,name,value):atomic(self.directory/name,json.dumps(value,ensure_ascii=False).encode())
    def _config(self):
        complete={name:value['last_success'] for name,value in self.sources.items()}
        checked={name:value['last_checked'] for name,value in self.sources.items()}
        self._save('config.json',dict(enabled=self.enabled,logged_out=self.state=='idle',inventory_epoch=self.inventory_epoch,last_checked=self.last_checked,last_received=self.last_received,last_success=self.last_received,source_checked=checked,source_complete_success=complete,source_success=complete,source_discovery_complete={name:value['discovery_complete'] for name,value in self.sources.items()},source_discovered_sections={name:list(value['discovered_sections']) for name,value in self.sources.items()},source_section_times={name:dict(value['discovered_section_times']) for name,value in self.sources.items()}))
    def status(self):
        with self.lock:
            state,error=self.state,self.last_error
            tick=time.monotonic();alive=self.process is not None and self.process.poll() is None
            stale=alive and self.heartbeat_tick is not None and tick-self.heartbeat_tick>HEARTBEAT_TIMEOUT
            source_values={}
            for name,value in self.sources.items():
                progress=self.source_ticks.get(name)
                freshness='paused' if not self.enabled else 'starting' if progress is None else 'stale' if tick-progress>PROGRESS_TIMEOUT else 'fresh'
                source_values[name]=dict(value,discovered_sections=list(value['discovered_sections']),discovered_section_times=dict(value['discovered_section_times']),freshness=freshness,last_complete_success=value['last_success'])
                if name=='notice':
                    source_values[name]['attachment_pending_count']=len(self.incomplete)
                    if self.incomplete and source_values[name]['state']=='connected':source_values[name].update(state='partial',coverage='partial',error=ERRORS['attachment'])
                if freshness=='stale' and value['state'] in {'connecting','syncing'}:stale=True
            if stale and self.enabled:state='retrying';error=ERRORS['stalled']
            if self.enabled and state in {'connected','syncing','partial'}:
                issues=[value for value in source_values.values() if value['state'] in {'retrying','partial','error','expired'} or (value['state'] in {'connecting','syncing'} and value['error'])]
                if issues:
                    state='expired' if any(value['state']=='expired' for value in issues) else 'partial'
                    error=ERRORS['expired'] if state=='expired' else ' '.join(dict.fromkeys(value['error'] for value in issues if value['error']))
            freshness='paused' if not self.enabled else 'stale' if stale else 'offline' if not alive and self.restart_at is not None else 'starting' if self.last_heartbeat is None else 'fresh' if alive else 'offline'
            return dict(enabled=self.enabled,state=state,inventory_epoch=self.inventory_epoch,qr_ready=self.qr_ready,last_checked=self.last_checked,last_received=self.last_received,last_success=self.last_received,last_error=(error or (ERRORS['attachment'] if self.incomplete else '')),incomplete=len(self.incomplete),queued=len(self.pending),last_count=self.last_count,session_saved=(self.directory/'session.bin').is_file(),error_stage=self.error_stage,error_code=self.error_code,retry_in=self.retry_in,sources=source_values,worker_alive=alive,last_heartbeat=self.last_heartbeat,restart_count=self.restart_count,next_retry_at=self.next_retry_at,freshness=freshness)
    def _watch(self):
        while not self.wake.wait(10):
            try:self._maintain_worker()
            except Exception:pass
    def _lost_worker(self,epoch,code='worker_exit'):
        with self.lock:
            if not self._current(epoch) or self.restart_at is not None:return
            self.qr_ready=False;self.error_stage='worker';self.error_code=code
            if self.restart_attempts>=MAX_RESTARTS:
                self.state='error';self.last_error=ERRORS['runtime'];self.retry_in=0;return
            self.retry_in=min(300,10*2**self.restart_attempts);self.restart_at=time.monotonic()+self.retry_in
            self.next_retry_at=(datetime.now(timezone.utc)+timedelta(seconds=self.retry_in)).isoformat()
            self.state='retrying';self.last_error=ERRORS['stalled' if code=='stalled' else 'worker']
            self._save('diagnostic.json',dict(at=now_iso(),state=self.state,stage='worker',reason=code,retry_in=self.retry_in))
    def _maintain_worker(self):
        with self.lock:
            if not self.enabled or self.closed:return
            epoch=self.epoch;tick=time.monotonic();process=self.process
            stale=process is not None and process.poll() is None and self.heartbeat_tick is not None and tick-self.heartbeat_tick>HEARTBEAT_TIMEOUT
            stalled=any(tick-value>PROGRESS_TIMEOUT for value in self.source_started.values())
            if process is not None and process.poll() is not None:self._lost_worker(epoch)
            if stale or stalled:
                self._lost_worker(epoch,'stalled')
                if self.restart_at is not None:self.restart_at=tick
            restart=self.restart_at is not None and tick>=self.restart_at
            retry_queue=bool(self.pending) and tick-self.queue_retry_tick>=15
            if retry_queue:self.queue_retry_tick=tick
        if retry_queue:self.retry_pending()
        if process is not None and process.poll() is None and not restart:self.repair_tasks(automatic=True)
        if restart:
            with self.control:
                with self.lock:
                    if not self._current(epoch):return
                    self.restart_count+=1;self.restart_attempts+=1
                self._start(False,False)
    def recheck(self):
        with self.control:
            with self.lock:
                if self.closed:return self.status()
                alive=self.enabled and self.process is not None and self.process.poll() is None
                self.restart_attempts=0
            if not alive:return self._start(False,False)
            self.retry_pending();self.command(dict(type='recheck'));return self.status()
    def task_inventory(self,limit=20,offset=0,attention_only=False):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:raise ValidationError('核对清单分页参数无效。')
        with self.lock:
            report=self.inventory.snapshot()
            attention=[item for item in report['items'] if item['state'] in ('missing','unrecognized','pending')]
            report.update(source_total=report['total'],attention_count=len(attention),
                          attention_detail_pending=sum(item['detail_state']=='pending' for item in attention),
                          attention_deadline_pending=sum(item.get('deadline_pending',False) for item in attention),
                          attention_manual_details=sum(item['detail_state']=='manual' or item['media_pending'] for item in attention))
            if attention_only:report.update(items=attention,total=len(attention))
            offset=min(offset,max(0,(report['total']-1)//limit)*limit)
            report.update(items=report['items'][offset:offset+limit],limit=limit,offset=offset,enabled=self.enabled,attention_only=attention_only)
            return report
    def repair_tasks(self,keys=None,automatic=False,sections=None):
        with self.lock:
            if not self.enabled or self.closed:raise ValidationError('请先恢复学习通同步，再补收任务。')
            if sections is not None and (keys is not None or not isinstance(sections,list) or not 1<=len(sections)<=50 or any(not isinstance(key,str) or key not in self.inventory.data['sections'] for key in sections)):raise ValidationError('请选择清单中的有效课程栏目。')
            report=self.inventory.snapshot();selected=[] if sections is not None else self.inventory.repair_keys(report,keys,automatic)
            section_keys=list(dict.fromkeys(sections or []))
            if automatic:
                tick=time.time()
                for section in report['sections']:
                    value=self.inventory.data['sections'][section['key']]
                    if section['state']=='checked' and section['freshness']=='fresh':continue
                    if tick<value.get('retry_after',0):continue
                    section_keys.append(section['key'])
                    if len(section_keys)>=2:break
            for key in section_keys:self.inventory.data['sections'][key]['retry_after']=time.time()+60
            repaired=0
            for item in report['items']:
                if item['key'] in selected and item['state']=='unrecognized':
                    try:repaired+=len(self.inbox.retry_task_extraction(item['message_id']))
                    except (ValidationError,ValueError):pass
            self._save('task-inventory.json',self.inventory.data)
            if selected:self.command(dict(type='repair_tasks',keys=selected))
            if section_keys:self.command(dict(type='repair_sections',keys=section_keys))
            return dict(requested=len(selected),reextracted=repaired,sections_requested=len(section_keys))
    def qr(self):
        with self.lock:
            if not self.enabled or not self.qr_ready or self.state!='waiting_scan':return None
            path=self.directory/'qr.png'
            try:
                image=path.read_bytes()
                return image if len(image)<=2*1024*1024 and image.startswith(b'\x89PNG') else None
            except OSError:return None
    def command(self,value):
        with self.lock:
            if self.process and self.process.poll() is None:
                try:self.process.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.process.stdin.flush()
                except (OSError,BrokenPipeError):pass
    def _runtime(self):
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
        node=os.environ.get('CI_NODE') or (str(bundled/'bin/node.exe') if (bundled/'bin/node.exe').is_file() else shutil.which('node'))
        if not node:raise ValidationError(ERRORS['runtime'])
        env=dict(os.environ)
        for name in list(env):
            if name.startswith('CI_MODEL_') or name=='CI_ACCESS_TOKEN':env.pop(name)
        if (bundled/'node_modules/playwright').is_dir():env['NODE_PATH']=str(bundled/'node_modules')
        return node,env
    def start(self,fresh=False,visible=False):
        with self.control:return self._start(fresh,visible)
    def _start(self,fresh=False,visible=False):
        self._stop_worker()
        with self.lock:
            if self.closed:return self.status()
            self.enabled=True;self.state='connecting';self.last_error='';self.error_stage='';self.error_code='';self.retry_in=0;self.qr_ready=False
            if fresh:
                self.inventory_epoch+=1
                self.inventory=TaskInventory(self.inbox);self._save('task-inventory.json',self.inventory.data)
                for value in self.sources.values():value.update(discovery_complete=False,discovered_sections=[],discovered_section_times={})
            self.restart_at=self.next_retry_at=None;self.last_heartbeat=None;self.heartbeat_tick=time.monotonic();self.source_ticks.clear();self.source_started.clear()
            for value in self.sources.values():value.update(state='connecting',error='',stage='',reason='',issue_summary='')
            self._config();self.epoch+=1;epoch=self.epoch
            self.retry_pending()
            try:
                node,env=self._runtime();session=None
                if not fresh and (self.directory/'session.bin').is_file():session=json.loads(unseal((self.directory/'session.bin').read_bytes()))
                self.process=subprocess.Popen([node,str(self.root/'desktop-sync/worker.cjs'),str(self.directory)],cwd=self.root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                process=self.process;self.reader=threading.Thread(target=self._read,args=(process,epoch),daemon=True);self.reader.start()
                self.command(dict(type='start',session=session,visible=visible,accepted=list(self.accepted)))
            except ValidationError as error:self.state='error';self.last_error=str(error);self.error_stage=self.error_code='runtime'
            except Exception:
                self.state='error';self.error_stage=self.error_code='session' if (self.directory/'session.bin').is_file() and not fresh else 'runtime';self.last_error=ERRORS[self.error_code]
            return self.status()
    def _read(self,process,epoch):
        try:
            for line in process.stdout:
                if len(line)>12*1024*1024:continue
                try:message=json.loads(line)
                except ValueError:continue
                self.receive(message,epoch)
        finally:
            with self.lock:
                if epoch==self.epoch and self.process is process:self._lost_worker(epoch)
    def _current(self,epoch):return self.enabled and not self.closed and (epoch is None or epoch==self.epoch)
    def receive(self,message,epoch=None):
        with self.lock:
            if not self._current(epoch):return
        kind=message.get('type')
        if kind=='task_inventory':
            with self.lock:
                if not self._current(epoch):return
                self.inventory.receive(message);self._save('task-inventory.json',self.inventory.data)
            return
        if kind=='heartbeat':
            with self.lock:
                if self._current(epoch):self.last_heartbeat=now_iso();self.heartbeat_tick=time.monotonic()
            return
        if kind=='source':
            with self.lock:
                if not self._current(epoch):return
                name=message.get('source');state=message.get('state')
                if name not in self.sources or state not in {'idle','connecting','syncing','connected','retrying','partial','expired','error'}:return
                value=self.sources[name]
                self.source_ticks[name]=time.monotonic();value['last_progress']=now_iso()
                if state in {'connecting','syncing'}:self.source_started[name]=time.monotonic()
                else:self.source_started.pop(name,None)
                if name!='task_center' and state in {'connecting','syncing'} and value['error']:return
                value.update(state=state,error=ERRORS.get(message.get('error'),''),stage=message.get('stage') if message.get('stage') in STAGES else '',reason=message.get('reason') if message.get('reason') in REASONS else '')
                for field in ('checked_count','captured_count','failed_count','pending_count','detail_pending_count','unsupported_detail_count','media_pending_count'):
                    count=message.get(field)
                    if type(count) is int and 0<=count<=1000000:value[field]=count
                if message.get('coverage') in COVERAGE:value['coverage']=message['coverage']
                if message.get('discovery_complete') is True:value['discovery_complete']=True
                discovered=section_keys(message.get('discovered_sections'))
                if discovered:
                    merged=section_keys(value['discovered_sections']+discovered)
                    stamp=datetime.now(timezone.utc).isoformat(timespec='microseconds')
                    times={key:value['discovered_section_times'].get(key,stamp) for key in merged}
                    if merged!=value['discovered_sections'] or times!=value['discovered_section_times']:
                        value.update(discovered_sections=merged,discovered_section_times=times);self._config()
                if name=='notice' and self.incomplete:value['coverage']='partial'
                if name=='task_center' and isinstance(message.get('issues'),list):
                    labels={'assignment':'作业','exam':'考试','course':'课程入口'}
                    valid=[f"第{item['course_index']}门课{labels[item['section']]}" for item in message['issues'][:10] if isinstance(item,dict) and type(item.get('course_index')) is int and 1<=item['course_index']<=100 and type(item.get('section')) is str and item['section'] in labels]
                    value['issue_summary']='、'.join(valid[:3])
                if name=='chat' and isinstance(message.get('issues'),list):
                    valid=[f"第{item['conversation_index']}个会话" for item in message['issues'][:10] if isinstance(item,dict) and type(item.get('conversation_index')) is int and 1<=item['conversation_index']<=1000]
                    value['issue_summary']='、'.join(valid[:3])
                if name=='notice' and isinstance(message.get('issues'),list):
                    valid=[f"第{item['notice_index']}条通知" for item in message['issues'][:10] if isinstance(item,dict) and type(item.get('notice_index')) is int and 1<=item['notice_index']<=1000]
                    value['issue_summary']='、'.join(valid[:3])
                if state=='connected' and (value['pending_count'] or value['failed_count'] or value['detail_pending_count'] or value['unsupported_detail_count'] or value['media_pending_count'] or value['coverage'] in {'partial','list_only'}):
                    state='partial';value.update(state=state,error=ERRORS['coverage'] if value['coverage']=='list_only' or value['media_pending_count'] else ERRORS[name])
                if message.get('checked') is True and state in {'connected','partial','syncing'}:
                    checked_at=now_iso();value['last_checked']=checked_at;self.last_checked=checked_at
                    if state=='connected':value['last_success']=checked_at;self.restart_attempts=0
                    self._config()
            return
        if kind=='status':
            with self.lock:
                if not self._current(epoch):return
                if message.get('state') in STATES:self.state=message['state']
                self.qr_ready=message.get('qr_ready') is True and self.state=='waiting_scan'
                self.last_error=ERRORS.get(message.get('error'),'')
                self.error_stage=message.get('stage') if message.get('stage') in STAGES else ''
                self.error_code=message.get('reason') if message.get('reason') in REASONS else ''
                seconds=message.get('retry_in',0);self.retry_in=min(60,max(0,seconds)) if type(seconds) is int else 0
                if self.error_stage or self.error_code:self._save('diagnostic.json',dict(at=now_iso(),state=self.state,stage=self.error_stage,reason=self.error_code,retry_in=self.retry_in))
                if message.get('checked') is True and self.state in {'connected','partial'}:self.last_checked=now_iso();self._config()
            return
        if kind=='session':
            try:
                value=message['session'];raw=json.dumps(value).encode()
                if not isinstance(value,dict) or len(raw)>2*1024*1024:raise ValueError()
                with self.lock:
                    if not self._current(epoch):return
                    atomic(self.directory/'session.bin',seal(raw))
            except Exception:
                with self.lock:
                    if self._current(epoch):self.last_error=ERRORS['session']
            return
        if kind not in {'notice','chat','task_center','checkin_activity'} or not isinstance(message.get('job'),dict):return
        if message['job'].get('kind','chat')!={'notice':'course_notice','chat':'chat','task_center':'task_center','checkin_activity':'checkin_activity'}[kind]:return
        job=message['job'];budget=max(0,min(20000,30000-len(job.get('text',''))-len(job.get('title',''))-sum(len(a.get('name',''))+220 for a in job.get('attachments',[]))-400))
        for attachment in job.get('attachments',[]):
            encoded=attachment.pop('content_base64',None)
            if encoded is not None:
                try:
                    if not isinstance(encoded,str) or len(encoded)>12*1024*1024:raise ValueError()
                    raw=base64.b64decode(encoded,validate=True)
                    if len(raw)>MAX_UPLOAD or not budget:raise ValueError()
                    text,engine=extract_file(attachment['name'],raw,self.root)
                    if not text.strip():raise ValueError()
                    attachment['text']=text[:budget];attachment['status']='partial' if len(text)>budget or engine.endswith('/partial') else 'extracted';budget-=len(attachment['text']);attachment['error']='仅部分附件文字，请核对原文件。' if attachment['status']=='partial' else ''
                except Exception:attachment.update(status='failed',text='',error='说明附件文字提取失败，请核对原文件。')
        with self.lock:
            if not self._current(epoch):return
            previous=next((i for i,p in enumerate(self.pending) if p.get('message_id')==job.get('message_id')),None)
            if kind=='task_center':
                incomplete_repeat=self.inventory.incomplete_repeat(job)
                self.inventory.record(job);self._save('task-inventory.json',self.inventory.data)
                if incomplete_repeat:
                    self.accepted.add(job['message_id']);self._save('accepted.json',list(self.accepted)[-10000:])
                    self.command(dict(type='accepted',id=job['message_id'],complete=True));return
            if previous is not None:self.pending[previous]=job
            elif len(self.pending)<500 and len(json.dumps(self.pending,ensure_ascii=False))+len(json.dumps(job,ensure_ascii=False))<=1500000:self.pending.append(job)
            else:self.last_error='待传队列已满，请先处理已收到的通知。';return
            self._save('pending.json',self.pending)
        self.retry_pending()
    def retry_pending(self):
        with self.lock:
            if not self.enabled:return
            for job in list(self.pending):
                try:result=ingest_web_message(self.inbox,job)
                except Exception:self.last_error=ERRORS['queue'];continue
                if result.get('deferred'):
                    self.pending.remove(job)
                    continue
                if job.get('kind')=='task_center':
                    from .chaoxing import task_payload
                    from .task_identity import platform_identity
                    stored=result['message']
                    if result.get('cleared'):
                        with self.inbox.connection() as db:
                            tombstone=db.execute("SELECT fingerprint FROM cleared_messages WHERE message_id=? AND fingerprint LIKE 'task-capture:%' LIMIT 1",(stored['id'],)).fetchone()
                        entry=self.inventory.data['items'].get(platform_identity(job.get('url','')))
                        if tombstone and entry:entry['content_key']=tombstone['fingerprint']
                        self._save('task-inventory.json',self.inventory.data)
                    elif stored.get('external',{}).get('task_body'):
                        self.inventory.record(task_payload(stored['external'],stored['course'],stored['scope'],stored['captured_at']))
                        if result.get('attachment_conflict'):
                            entry=self.inventory.data['items'].get(platform_identity(job.get('url','')))
                            if entry:entry['media_pending']=True;entry['receipt_media_complete']=False
                        self._save('task-inventory.json',self.inventory.data)
                self.pending.remove(job)
                if not result['duplicate']:self.last_received=now_iso()
                self.last_count+=not result['duplicate']
                attachments=result['message'].get('external',{}).get('attachments',[]) if job.get('kind') in ('course_notice','task_center') else []
                retryable=bool(result.get('attachment_conflict')) or any(a.get('status')=='failed' for a in attachments)
                gap=retryable or any(a.get('status') in {'partial','skipped','listed'} for a in attachments) or bool(result['message'].get('external',{}).get('media_pending_count'))
                if not retryable:self.accepted.add(job['message_id'])
                if gap:self.incomplete.add(job['message_id']);self.last_error=ERRORS['attachment']
                else:self.incomplete.discard(job['message_id'])
                self.command(dict(type='accepted',id=job['message_id'],complete=not retryable,media_complete=not gap))
            self._save('pending.json',self.pending);self._save('accepted.json',list(self.accepted)[-10000:]);self._save('incomplete.json',list(self.incomplete));self._config()
    def _stop_worker(self):
        with self.lock:
            self.inventory.current_sections.clear()
            self.epoch+=1;process=self.process;self.process=None;self.restart_at=self.next_retry_at=None;self.source_started.clear()
        if process and process.poll() is None:
            try:process.stdin.write('{"type":"close"}\n');process.stdin.flush();process.wait(timeout=4)
            except (OSError,subprocess.TimeoutExpired):
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:pass
    def pause(self):
        with self.control:
            with self.lock:self.enabled=False;self.state='paused';self.qr_ready=False;self._config()
            self._stop_worker();return self.status()
    def logout(self):
        with self.control:
            with self.lock:
                self.enabled=False;self.state='idle';self.qr_ready=False;self.last_checked=None;self.last_received=None;self.last_error='';self.error_stage='';self.error_code='';self.retry_in=0
                self.inventory_epoch+=1
                self.inventory=TaskInventory(self.inbox);self._save('task-inventory.json',self.inventory.data)
                for value in self.sources.values():value.update(state='idle',last_checked=None,last_success=None,discovery_complete=False,discovered_sections=[],discovered_section_times={},checked_count=0,captured_count=0,failed_count=0,pending_count=0,error='',stage='',reason='',issue_summary='')
            self._stop_worker()
            with self.lock:
                for name in ('session.bin','qr.png','diagnostic.json'):
                    try:(self.directory/name).unlink()
                    except FileNotFoundError:pass
                self._config()
                return self.status()
    def close(self):
        with self.control:
            with self.lock:self.closed=True;self.qr_ready=False;self.wake.set()
            self._stop_worker()
