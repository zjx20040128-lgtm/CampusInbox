"""Authenticated local HTTP API; no dependency beyond Python stdlib."""
import base64
import binascii
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import socket
from datetime import datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,quote
from .core import ValidationError,Conflict,NotFound,now_iso,CN,parse_timestamp
from .agent import Agent,AgentError,provider_from_env
from .files import extract_file
from .discovery import DiscoveryService
from .desktop_sync import DesktopSync
from .desktop_alerts import DesktopAlerts
from .mobile_reminders import MobileReminders
from .acceptance import desktop_acceptance_report
from .evaluation_web import EvaluationWorkspace
from .original_files import OriginalFiles
from .chaoxing import scoped_token, extension_origin, ingest_web_message, SOURCE as WEB_SOURCE, NOTICE_SOURCE, TASK_SOURCE

MAX_BODY=12*1024*1024
WEB_WRITE_PATHS=('/api/chaoxing/messages','/api/chaoxing/attachments/extract')
DESKTOP_PATHS=('/api/chaoxing/desktop/status','/api/chaoxing/desktop/login','/api/chaoxing/desktop/resume','/api/chaoxing/desktop/pause','/api/chaoxing/desktop/logout','/api/chaoxing/desktop/qr','/api/chaoxing/desktop/recheck','/api/chaoxing/desktop/acceptance','/api/chaoxing/desktop/inventory','/api/chaoxing/desktop/repair')
ALERT_PATHS=('/api/desktop/alerts','/api/desktop/alerts/ack','/api/desktop/alerts/settings')
REMINDER_PATHS=('/api/mobile-reminders/status','/api/mobile-reminders/settings','/api/mobile-reminders/pairing','/api/mobile-reminders/revoke')
WECHAT_PATHS=('/api/wechat-push/status','/api/wechat-push/settings','/api/wechat-push/test')
DEFAULT_PACKAGES=['com.chaoxing.mobile']
PACKAGE_RE=re.compile(r'[A-Za-z][\w]*(?:\.[A-Za-z][\w]*)+')

def load_settings(directory):
    path=Path(directory)/'settings.json'
    if path.exists():
        try:
            obj=json.loads(path.read_text(encoding='utf-8-sig'))
            packages=obj['allowed_packages']
            if isinstance(packages,list) and all(isinstance(p,str) and PACKAGE_RE.fullmatch(p) for p in packages):
                return {'allowed_packages':packages[:30]}
        except (ValueError,KeyError,TypeError,OSError): pass
    return {'allowed_packages':DEFAULT_PACKAGES.copy()}

def create_server(host,port,inbox,token,root=None,agent=None,*,reminder_port=8766):
    root=Path(root or Path(__file__).resolve().parents[1])
    configured=agent or Agent(inbox,provider_from_env())
    settings=load_settings(inbox.path.parent)
    web_token=scoped_token(token)
    class Handler(BaseHTTPRequestHandler):
        server_version='CourseInbox/0.1'
        protocol_version='HTTP/1.0'
        def log_message(self,fmt,*args):
            # Requests may contain credential-like strings; no URL/body logging.
            pass
        def response(self,status,payload,kind='application/json; charset=utf-8',filename=None):
            # Avoid resetting a small rejected upload with unread bytes on Windows.
            if status>=400 and not getattr(self,'body_consumed',False) and not self.headers.get('Transfer-Encoding'):
                try: pending=int(self.headers.get('Content-Length','0'))
                except ValueError: pending=0
                if 0<pending<=65536:
                    self.connection.settimeout(0.5)
                    try: self.rfile.read(pending)
                    except (ConnectionError,socket.timeout): pass
                    finally: self.connection.settimeout(15)
            if isinstance(payload,(dict,list)):
                payload=json.dumps(payload,ensure_ascii=False).encode('utf-8')
            elif isinstance(payload,str):
                payload=payload.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            origin=self.headers.get('Origin')
            if urlsplit(self.path).path in WEB_WRITE_PATHS and extension_origin(origin):
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Access-Control-Allow-Methods','POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
                self.send_header('Vary','Origin')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                safe=re.sub(r'[^A-Za-z0-9._-]','_',filename)
                self.send_header('Content-Disposition',f'attachment; filename="{safe}"; filename*=UTF-8\'\'{quote(filename,safe="")}')
            self.end_headers()
            self.wfile.write(payload)
        def guard(self):
            raw_host=self.headers.get('Host','')
            try:
                target=urlsplit('http://'+raw_host)
                host_name=target.hostname
                port_number=target.port or 80
            except ValueError:
                return self.response(403,{'error':'Host 无效。'}) or False
            if host_name not in self.server.discovery.allowed_hosts() or port_number!=self.server.server_port or target.path:
                return self.response(403,{'error':'此 Host 未授权。'}) or False
            origin=self.headers.get('Origin')
            path=urlsplit(self.path).path
            if path.startswith('/api/evaluation/') or re.fullmatch(r'/api/messages/[a-f0-9]{32}/attachments/\d+/download',path) or path in (*WEB_WRITE_PATHS,'/api/chaoxing/pairing',*DESKTOP_PATHS,*ALERT_PATHS,*REMINDER_PATHS,*WECHAT_PATHS):
                if host_name not in ('127.0.0.1','localhost','::1') or not ipaddress.ip_address(self.client_address[0]).is_loopback:
                    return self.response(403,{'error':'网页正文同步仅允许本机连接。'}) or False
            if origin:
                if origin!='http://'+raw_host and not (path in WEB_WRITE_PATHS and extension_origin(origin)):
                    return self.response(403,{'error':'请求来源未授权。'}) or False
            return True
        def auth(self):
            header=self.headers.get('Authorization','')
            if not hmac.compare_digest(header,'Bearer '+token):
                self.response(401,{'error':'需要访问令牌。本机打开可自动连接，手机请填写令牌。'})
                return False
            return True
        def body(self):
            value=self.headers.get('Content-Length')
            try: size=int(value or '0')
            except ValueError: raise ValidationError('Content-Length 无效。') from None
            if size<0 or size>MAX_BODY: raise ValidationError('请求超过 12 MB 上限。')
            if self.headers.get('Transfer-Encoding'): raise ValidationError('不支持分块上传。')
            if 'application/json' not in self.headers.get('Content-Type',''): raise ValidationError('请使用 JSON 请求。')
            self.body_consumed=True
            try: result=json.loads(self.rfile.read(size))
            except (ValueError,UnicodeDecodeError): raise ValidationError('JSON 无效。') from None
            if not isinstance(result,dict): raise ValidationError('请求体必须为 JSON 对象。')
            return result
        def do_GET(self): self.handle_route('GET')
        def do_POST(self): self.handle_route('POST')
        def do_PATCH(self): self.handle_route('PATCH')
        def do_OPTIONS(self): self.handle_route('OPTIONS')
        def handle_route(self,method):
            try:
                self.connection.settimeout(15)
                if not self.guard(): return
                path=urlsplit(self.path).path
                if method=='OPTIONS' and path in WEB_WRITE_PATHS and extension_origin(self.headers.get('Origin')):
                    return self.response(204,b'')
                if method=='GET' and path=='/api/health':
                    return self.response(200,{'status':'ok','app':'CourseInbox','version':'0.1.0'})
                if method=='GET' and path=='/api/mobile/pairing':
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    challenges=query.get('challenge',[])
                    if set(query)!={'challenge'} or len(challenges)!=1 or not re.fullmatch('[0-9a-f]{64}',challenges[0]):
                        raise ValidationError('配对挑战无效。')
                    address=urlsplit('http://'+self.headers['Host']).hostname
                    try: result=self.server.discovery.pairing(challenges[0],address)
                    except ValueError: raise ValidationError('配对需使用电脑 IPv4 地址。') from None
                    return self.response(200,result)
                if method=='GET' and path=='/api/bootstrap':
                    host_name=urlsplit('http://'+self.headers['Host']).hostname
                    if not ipaddress.ip_address(self.client_address[0]).is_loopback or host_name not in ('localhost','127.0.0.1','::1'):
                        return self.response(403,{'error':'远程访问请手动输入本机令牌。'})
                    return self.response(200,{'token':token})
                if not path.startswith('/api/'):
                    if method!='GET': return self.response(405,{'error':'方法不支持。'})
                    apk_name=path.removeprefix('/downloads/')
                    if path=='/downloads/courseinbox-browser-companion.zip':
                        bundle=root/'artifacts'/'browser'/'courseinbox-browser-companion.zip'
                        if not bundle.is_file(): return self.response(404,{'error':'浏览器组件尚未打包。'})
                        return self.response(200,bundle.read_bytes(),'application/zip',bundle.name)
                    if path.startswith('/downloads/') and apk_name in ('courseinbox-companion-0.2.2-debug.apk','courseinbox-companion-0.2.3-debug.apk','courseinbox-companion-0.2.4-debug.apk','courseinbox-companion-0.2.5-debug.apk','courseinbox-learning-0.3.0-debug.apk','courseinbox-learning-0.3.1-debug.apk','courseinbox-learning-0.3.2-debug.apk','courseinbox-learning-0.3.3-debug.apk','courseinbox-learning-0.3.4-debug.apk','courseinbox-learning-0.3.5-debug.apk','courseinbox-learning-0.3.6-debug.apk','courseinbox-learning-0.3.7-debug.apk','courseinbox-learning-0.3.8-debug.apk','courseinbox-learning-0.3.9-debug.apk','courseinbox-learning-0.3.10-debug.apk','courseinbox-learning-0.3.11-debug.apk','courseinbox-learning-0.3.12-debug.apk','courseinbox-learning-0.3.13-debug.apk','courseinbox-learning-0.3.14-debug.apk','courseinbox-learning-0.3.15-debug.apk','courseinbox-learning-0.3.16-debug.apk','courseinbox-learning-0.3.17-debug.apk','courseinbox-learning-0.3.18-debug.apk','courseinbox-learning-0.3.19-debug.apk','courseinbox-learning-0.3.20-debug.apk','courseinbox-learning-0.3.20-arm64-debug.apk','courseinbox-learning-0.3.20-universal-debug.apk','courseinbox-learning-0.3.21-debug.apk','courseinbox-learning-0.3.21-arm64-debug.apk'):
                        apk=root/'artifacts'/'mobile'/apk_name
                        if not apk.is_file(): return self.response(404,{'error':'安装包尚未构建。'})
                        return self.response(200,apk.read_bytes(),'application/vnd.android.package-archive',apk_name)
                    static={'/':'index.html' ,'/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg','/evaluation.js':'evaluation.js','/evaluation.css':'evaluation.css'}
                    target=static.get(path)
                    if not target or not (root/'web'/target).is_file():
                        return self.response(404,{'error':'页面不存在。'})
                    kind=mimetypes.guess_type(target)[0] or 'application/octet-stream'
                    if kind.startswith('text/') or kind=='application/javascript': kind+='; charset=utf-8'
                    return self.response(200,(root/'web'/target).read_bytes(),kind)
                if method=='POST' and path in WEB_WRITE_PATHS:
                    if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+web_token):
                        return self.response(401,{'error':'网页同步令牌无效，请重新配置浏览器组件。'})
                    body=self.body()
                    if path=='/api/chaoxing/attachments/extract':
                        if set(body)-{'filename','content_base64'}: raise ValidationError('附件字段不支持。')
                        name=body.get('filename','')
                        if not isinstance(name,str) or len(name)>180 or Path(name).suffix.lower() not in ('.docx','.pdf','.txt','.md','.png','.jpg','.jpeg','.bmp','.webp'):
                            raise ValidationError('仅支持文档、PDF、图片和 UTF-8 文本附件。')
                        raw=body.get('content_base64','')
                        if not isinstance(raw,str) or len(raw)>MAX_BODY: raise ValidationError('附件内容无效。')
                        try: data=base64.b64decode(raw,validate=True)
                        except (ValueError,binascii.Error): raise ValidationError('附件编码无效。') from None
                        text,engine=extract_file(name,data,root)
                        return self.response(200,dict(text=text[:20000],engine=engine,truncated=len(text)>20000 or engine.endswith('/partial')))
                    result=ingest_web_message(inbox,body)
                    acknowledgement={'accepted':True,'duplicate':result['duplicate']}
                    if any(a.get('status')=='failed' for a in result['message'].get('external',{}).get('attachments',[])): acknowledgement['attachment_pending']=True
                    if result.get('attachment_conflict'): acknowledgement['attachment_conflict']=True
                    return self.response(200 if result['duplicate'] else 201,acknowledgement)
                if not self.auth(): return
                if path.startswith('/api/evaluation/'):
                    try:
                        result,filename=self.server.evaluation.handle(method,path,parse_qs(urlsplit(self.path).query),self.body() if method=='POST' else {})
                        return self.response(200,result,filename=filename)
                    except Conflict as error:return self.response(409,{'error':str(error)})
                    except NotFound as error:return self.response(404,{'error':str(error)})
                if path in WECHAT_PATHS:
                    service=self.server.mobile_reminders.wechat
                    if method=='GET' and path.endswith('/status'):return self.response(200,service.status())
                    if method=='POST':
                        body=self.body()
                        if path.endswith('/settings'):return self.response(200,service.configure(body))
                        if path.endswith('/test') and not body:return self.response(200,service.test())
                    return self.response(405,dict(error='方法或参数不支持。'))
                if path in REMINDER_PATHS:
                    service=self.server.mobile_reminders
                    if method=='GET' and path.endswith('/status'):return self.response(200,service.status())
                    if method=='POST':
                        body=self.body()
                        if path.endswith('/settings') and set(body)=={'enabled'}:return self.response(200,service.configure(body['enabled']))
                        if path.endswith('/pairing') and not body:return self.response(200,service.make_pairing())
                        if path.endswith('/revoke') and set(body)=={'id'}:return self.response(200,service.revoke(body['id']))
                        raise ValidationError('手机提醒服务参数无效。')
                    return self.response(405,dict(error='方法不支持。'))
                if path in ALERT_PATHS:
                    if method=='GET' and path=='/api/desktop/alerts':return self.response(200,self.server.desktop_alerts.poll(sync_status=self.server.desktop_sync.status()))
                    if method=='POST':
                        body=self.body()
                        if path.endswith('/ack') and set(body)=={'ids'}:return self.response(200,self.server.desktop_alerts.ack(body['ids']))
                        if path.endswith('/settings') and set(body)=={'enabled'}:return self.response(200,self.server.desktop_alerts.settings(body['enabled']))
                        raise ValidationError('桌面提醒参数无效。')
                    return self.response(405,{'error':'方法不支持。'})
                if path in DESKTOP_PATHS:
                    if method=='GET' and path.endswith('/inventory'):
                        query=parse_qs(urlsplit(self.path).query)
                        try:limit=int(query.get('limit',['20'])[0]);offset=int(query.get('offset',['0'])[0])
                        except ValueError:raise ValidationError('核对清单分页参数无效。') from None
                        scope=query.get('scope',['all'])[0]
                        if scope not in ('all','attention'):raise ValidationError('核对清单范围无效。')
                        return self.response(200,self.server.desktop_sync.task_inventory(limit,offset,attention_only=scope=='attention'))
                    if method=='GET' and path.endswith('/acceptance'):return self.response(200,desktop_acceptance_report(inbox,self.server.desktop_sync.status(),configured.info(),self.server.desktop_sync.task_inventory(limit=1)),filename='courseinbox-desktop-check.json')
                    if method=='GET' and path.endswith('/status'):return self.response(200,self.server.desktop_sync.status())
                    if method=='GET' and path.endswith('/qr'):
                        image=self.server.desktop_sync.qr()
                        return self.response(200,image,'image/png') if image else self.response(404,{'error':'请先发起扫码登录。'})
                    if method=='POST':
                        body=self.body()
                        if path.endswith('/repair'):
                            if set(body)-{'keys','sections'} or ('keys' in body and 'sections' in body):raise ValidationError('任务补收参数无效。')
                            if any(not isinstance(body[key],list) for key in body):raise ValidationError('任务补收参数必须是清单数组。')
                            return self.response(200,self.server.desktop_sync.repair_tasks(body.get('keys'),sections=body.get('sections')))
                        if path.endswith('/logout'):
                            if body:raise ValidationError('退出登录不接受其他参数。')
                            return self.response(200,self.server.desktop_sync.logout())
                        if path.endswith('/recheck'):
                            if body:raise ValidationError('重新检查不接受其他参数。')
                            return self.response(200,self.server.desktop_sync.recheck())
                        if set(body)-{'visible'} or ('visible' in body and not isinstance(body['visible'],bool)):raise ValidationError('登录选项无效。')
                        if path.endswith('/login'):return self.response(200,self.server.desktop_sync.start(fresh=True,visible=body.get('visible',False)))
                        if path.endswith('/resume'):return self.response(200,self.server.desktop_sync.start())
                        if path.endswith('/pause'):return self.response(200,self.server.desktop_sync.pause())
                    return self.response(405,{'error':'方法不支持。'})
                if method=='GET':
                    if re.fullmatch(r'/api/messages/[a-f0-9]{32}/attachments/\d{1,2}/download',path):
                        parts=path.split('/');name,data=self.server.original_files.read(parts[3],int(parts[5]))
                        return self.response(200,data,'application/octet-stream',name)
                    if path=='/api/chaoxing/pairing':
                        return self.response(200,{'token':web_token,'endpoint':'http://127.0.0.1:'+str(self.server.server_port)})
                    if path=='/api/state':
                        messages=inbox.message_feed(limit=None)
                        return self.response(200,dict(tasks=inbox.tasks(),proposals=inbox.proposals(),archived_proposals=inbox.proposals('archived'),messages=messages[:500],message_total=len(messages),summary=inbox.dashboard(),agent=configured.info()))
                    if path=='/api/tasks': return self.response(200,inbox.tasks())
                    if path=='/api/messages': return self.response(200,inbox.message_feed())
                    if path=='/api/messages/page':
                        query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                        if set(query)-{'limit','offset','deadline_from','deadline_to'} or any(len(values)!=1 for values in query.values()) or any(not re.fullmatch(r'\d{1,8}',query[key][0]) for key in ('limit','offset') if key in query):raise ValidationError('消息分页参数无效。')
                        return self.response(200,inbox.message_page(int(query.get('limit',['50'])[0]),int(query.get('offset',['0'])[0]),deadline_from=query.get('deadline_from',[''])[0],deadline_to=query.get('deadline_to',[''])[0]))
                    if path=='/api/messages/cleanup-preview':return self.response(200,inbox.cleanup_preview())
                    if re.fullmatch(r'/api/messages/[a-f0-9]{32}/supplements',path):return self.response(200,inbox.supplement_context(path.split('/')[3]))
                    if re.fullmatch(r'/api/messages/[a-f0-9]{32}',path):return self.response(200,inbox.message_display(path.rsplit('/',1)[-1]))
                    if path=='/api/proposals': return self.response(200,inbox.proposals())
                    if path=='/api/dashboard': return self.response(200,inbox.dashboard())
                    if path=='/api/settings':
                        web_messages=[m for m in inbox.messages(limit=None,include_hidden=True) if m['source'] in (WEB_SOURCE,NOTICE_SOURCE,TASK_SOURCE)]
                        web_status={'received_count':len(web_messages),'chat_count':sum(m['source']==WEB_SOURCE for m in web_messages),'course_notice_count':sum(m['source']==NOTICE_SOURCE for m in web_messages),'task_center_count':sum(m['source']==TASK_SOURCE for m in web_messages),'latest_received_at':max(m['received_at'] for m in web_messages) if web_messages else None}
                        return self.response(200,dict(settings,agent=configured.info(),server_port=self.server.server_port,listen_host=host,addresses=sorted(self.server.discovery.allowed_hosts()),mobile_discovery=self.server.discovery.status(),chaoxing_web=web_status,ocr=os.name=='nt',pdf_optional=True))
                    if path=='/api/calendar.ics': return self.response(200,inbox.calendar(),'text/calendar; charset=utf-8','courseinbox.ics')
                    if path=='/api/export.json':
                        content=dict(version='0.1.0',exported_at=now_iso(),messages=inbox.messages(limit=None,include_hidden=True),proposals=inbox.proposals(None),tasks=[inbox.task_detail(t['id']) for t in inbox.tasks()])
                        return self.response(200,content,filename='courseinbox-backup.json')
                    if path.startswith('/api/tasks/'):
                        return self.response(200,inbox.task_detail(path.rsplit('/',1)[-1]))
                if method in ('POST','PATCH'):
                    body=self.body()
                    if method=='POST' and path=='/api/connectors/chat/import':
                        from .chat_import import ingest as ingest_chat
                        selected=body.get('mode','rules')
                        if selected=='agent' and not configured.provider:raise ValidationError('服务端尚未配置模型，请选择规则模式。')
                        result=ingest_chat(inbox,body,Agent(inbox) if selected=='rules' else configured)
                        return self.response(200 if result['duplicate'] else 201,result)
                    if method=='POST' and re.fullmatch(r'/api/messages/[a-f0-9]{32}/supplements',path):
                        result=inbox.supplement_message(path.split('/')[3],body)
                        return self.response(200 if result['duplicate'] else 201,result)
                    if method=='POST' and path=='/api/messages/clear':
                        if set(body)!={'ids'}:raise ValidationError('消息清理只接受确认前选定的消息标识。')
                        return self.response(200,inbox.clear_messages(body['ids']))
                    if method=='POST' and path=='/api/messages':
                        if set(body)-{'text','source','captured_at','course','scope','mode'}: raise ValidationError('消息字段不支持。')
                        text=body.get('text','')
                        at=body.get('captured_at') or now_iso()
                        selected=body.get('mode','default')
                        if selected not in ('rules','agent','default'): raise ValidationError('提取模式无效。')
                        selected_agent=Agent(inbox) if selected=='rules' else configured
                        if selected=='agent' and not configured.provider: raise ValidationError('服务端尚未配置模型，请选择规则模式。')
                        course,scope=body.get('course',''),body.get('scope','')
                        # Validate context before forwarding any source to a model.
                        from .core import clean_string
                        course=clean_string(course,'课程',100)
                        scope=clean_string(scope,'班级',100)
                        analysis=selected_agent.analyze(text,at,course,scope)
                        result=inbox.ingest(text,source=body.get('source','手动导入'),captured_at=at,course=course,scope=scope,
                                            candidates=analysis['candidates'],mode=analysis['mode'],trace=analysis['trace'])
                        result['answer'],result['limited']=analysis['answer'],analysis['limited']
                        return self.response(200 if result['duplicate'] else 201,result)
                    if method=='POST' and re.fullmatch(r'/api/messages/[a-f0-9]+/reanalyze',path):
                        if set(body)-{'mode'} or body.get('mode','rules')!='rules':
                            raise ValidationError('重新提取入口使用本地规则，请传空对象或 mode=rules。')
                        return self.response(200,inbox.reanalyze(path.split('/')[3]))
                    if method=='POST' and path=='/api/files/extract':
                        if set(body)-{'filename','content_base64'}: raise ValidationError('文件字段不支持。')
                        name=body.get('filename','')
                        if not isinstance(name,str) or len(name)>240: raise ValidationError('文件名无效。')
                        raw=body.get('content_base64','')
                        if not isinstance(raw,str) or len(raw)>MAX_BODY: raise ValidationError('文件内容无效。')
                        try: data=base64.b64decode(raw,validate=True)
                        except (ValueError,binascii.Error): raise ValidationError('文件编码无效。') from None
                        text,engine=extract_file(name,data,root)
                        if len(text)>30000: raise ValidationError('识别内容超过 30000 字，请分段导入。')
                        return self.response(200,{'text':text,'engine':engine,'needs_review':True,'partial':engine.endswith('/partial')})
                    if method=='POST' and re.fullmatch(r'/api/proposals/[a-f0-9]+/confirm',path):
                        ident=path.split('/')[3]
                        return self.response(200,inbox.confirm(ident,body))
                    if method=='POST' and re.fullmatch(r'/api/proposals/[a-f0-9]+/dismiss',path):
                        return self.response(200,inbox.dismiss(path.split('/')[3]))
                    if method=='PATCH' and re.fullmatch(r'/api/tasks/[a-f0-9]+',path):
                        return self.response(200,inbox.patch_task(path.rsplit('/',1)[-1],body))
                    if method=='POST' and re.fullmatch(r'/api/tasks/[a-f0-9]+/adopt-platform-status',path):
                        return self.response(200,inbox.adopt_platform_status(path.split('/')[3],body))
                    if method=='POST' and path=='/api/assistant':
                        return self.response(200,configured.ask(body.get('question',''),body.get('course',''),body.get('scope')))
                    if method=='POST' and path=='/api/settings':
                        if set(body)!={'allowed_packages'}: raise ValidationError('只支持设置应用包名白名单。')
                        packages=body['allowed_packages']
                        if not isinstance(packages,list) or len(packages)>30 or any(not isinstance(p,str) or not PACKAGE_RE.fullmatch(p) or len(p)>150 for p in packages): raise ValidationError('白名单为最多30个完整应用包名。')
                        settings['allowed_packages']=list(dict.fromkeys(packages))
                        directory=inbox.path.parent
                        directory.mkdir(exist_ok=True)
                        with inbox.lock:
                            target=directory/'settings.json'
                            temp=directory/'settings.json.tmp'
                            temp.write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
                            os.replace(temp,target)
                        return self.response(200,settings)
                    if method=='POST' and path=='/api/mobile/notifications':
                        from .core import clean_string
                        parse_timestamp(body.get('captured_at'))
                        package=clean_string(body.get('package_name',''),'应用包名',150,True)
                        if package not in settings['allowed_packages']:
                            return self.response(403,{'error':'应用不在接收白名单中。'})
                        title=clean_string(body.get('title',''),'通知标题',500)
                        text=clean_string(body.get('text',''),'通知正文',28000)
                        key=clean_string(body.get('notification_key',''),'通知标识',1000,True)
                        # The timestamp is required: relative dates belong to posted time, not upload time.
                        result=inbox.ingest('\n'.join(x for x in [title,text] if x),source='Android · '+package,captured_at=body.get('captured_at'),
                                            course=body.get('course',''),scope=body.get('scope',''),event_key=key)
                        return self.response(200 if result['duplicate'] else 201,result)
                    if method=='POST' and path=='/api/demo':
                        return self.response(200,seed_demo(inbox))
                return self.response(404,{'error':'接口不存在。'})
            except NotFound as e: self.response(404,{'error':str(e)})
            except Conflict as e: self.response(409,{'error':str(e)})
            except ValidationError as e: self.response(400,{'error':str(e)})
            except AgentError as e: self.response(502,{'error':str(e),'suggestion':'可显式改用规则提取后重试。'})
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,socket.timeout): pass
            except Exception:
                self.response(500,{'error':'本地服务发生异常，请查看启动窗口并保留当前输入。'})
    class Server(ThreadingHTTPServer):
        allow_reuse_address=os.name!='nt'
        def server_bind(self):
            if os.name=='nt' and hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            super().server_bind()
        def server_close(self):
            try:
                if hasattr(self,'evaluation'):self.evaluation.close()
                if hasattr(self,'mobile_reminders'):self.mobile_reminders.close()
                if hasattr(self,'desktop_sync'): self.desktop_sync.close()
                if hasattr(self,'discovery'): self.discovery.close()
            finally: super().server_close()
    server=Server((host,port),Handler)
    server.daemon_threads=True
    try:
        server.discovery=DiscoveryService(inbox.path.parent,token,host,server.server_port)
        server.discovery.start()
        server.desktop_sync=DesktopSync(inbox,root)
        server.original_files=OriginalFiles(inbox,root,server.desktop_sync._runtime)
        server.desktop_alerts=DesktopAlerts(inbox)
        server.evaluation=EvaluationWorkspace(inbox,root,configured)
        server.mobile_reminders=MobileReminders(inbox,server.desktop_alerts,server.discovery.identity['device_id'],server.desktop_sync.status,port=reminder_port)
    except Exception:
        server.server_close();raise
    return server

def seed_demo(inbox,current=None):
    current=(current if current is not None else datetime.now(CN)).replace(microsecond=0)
    stamp=min(current,current.replace(hour=9,minute=0,second=0)).isoformat()
    soon=(current+timedelta(hours=8)).replace(minute=0,second=0)
    later=current+timedelta(days=3)
    day=current+timedelta(days=5)
    notices=[
        f'《软件工程》 第三次作业：请提交实验报告、源代码。截止：{soon:%Y年%m月%d日 %H:%M}。',
        f'《高等数学》 第一次作业：请提交习题扫描件。截止：{later:%Y年%m月%d日} 20:00。',
        f'《数据库原理》 实验2：请提交 SQL 脚本、实验报告。截止：{day:%Y年%m月%d日} 18:00。'
    ]
    ids=[]
    for text in notices:
        result=inbox.ingest(text,source='示例 · 学习通',captured_at=stamp,scope='示例班级',sample=True)
        for p in result['proposals']:
            if p['status']=='confirmed': ids.append(p['task_id']); continue
            if p['before'] and not p['before']['sample']: continue
            try: ids.append(inbox.confirm(p['id'])['id'])
            except Conflict: pass
    # Missing deadline and extension are left for a person to confirm.
    inbox.ingest(f'《高等数学》 第一次作业原截止{later:%m月%d日}20:00，现延期到{(later+timedelta(days=1)):%m月%d日}18:00。',source='示例 · 班级群',captured_at=current.isoformat(),scope='示例班级',sample=True)
    inbox.ingest('《学术英语》 第二次作业：请提交演讲稿、演示文稿。具体截止时间稍后通知。',source='示例 · 课程通知',captured_at=stamp,scope='示例班级',sample=True)
    return dict(sample=True,message='已加载示例：3个已确认任务、延期草稿和缺少截止的草稿。',task_ids=ids)
