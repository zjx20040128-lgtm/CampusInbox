"""Visible web message intake. No platform credentials or platform API requests."""
import hashlib
import hmac
import re
from urllib.parse import urlsplit, parse_qsl
from .core import ValidationError, clean_string, parse_timestamp, validate_deadline, now_iso, parse_message
from .intake_policy import automatic_candidate

SOURCE = '学习通网页 · 聊天正文'
NOTICE_SOURCE = '学习通网页 · 课程通知'
TASK_SOURCE = '学习通网页 · 作业考试中心'


def scoped_token(token):
    return hmac.new(token.encode(), b'courseinbox:chaoxing-web:v1', hashlib.sha256).hexdigest()


def extension_origin(origin):
    return bool(re.fullmatch(r'chrome-extension://[a-p]{32}', origin or ''))


def safe_notice_url(value):
    value=clean_string(value,'通知链接',600)
    parsed=urlsplit(value)
    if parsed.scheme!='https' or parsed.netloc!='notice.chaoxing.com' or not re.fullmatch(r'/pc/notice/[^/]+/detail',parsed.path) or parsed.query or parsed.fragment:
        raise ValidationError('通知链接必须为学习通官方详情页。')
    return value


def safe_attachment_url(value):
    value=clean_string(value,'附件链接',300)
    if value and not re.fullmatch(r'https://d0\.cldisk\.com/download/[a-fA-F0-9]{32}',value):
        raise ValidationError('附件链接不在允许的下载范围。')
    return value


def safe_image_url(value):
    value=clean_string(value,'通知图片链接',800,True)
    parsed=urlsplit(value)
    if parsed.scheme!='https' or parsed.netloc!='p.ananas.chaoxing.com' or parsed.fragment or not re.search(r'\.(?:png|jpe?g|bmp|webp)$',parsed.path,re.I):
        raise ValidationError('通知图片必须为已支持的学习通官方图片链接。')
    return value


def safe_task_url(value):
    value=clean_string(value,'任务链接',800,True)
    parsed=urlsplit(value)
    if parsed.scheme!='https' or parsed.netloc not in ('mooc1.chaoxing.com','mooc2-ans.chaoxing.com') or not parsed.path.startswith('/') or parsed.username or parsed.password or parsed.fragment:
        raise ValidationError('任务链接必须为学习通官方作业或考试页面。')
    return value


def task_detail_url(value, original):
    """An explicit same-task description link, never an answer/start route."""
    from .task_identity import platform_identity
    if not value:return ''
    value=safe_task_url(value);parsed=urlsplit(value)
    if not re.fullmatch(r'/(?:mooc-ans/)?(?:mooc2/)?work/(?:view|detail)',parsed.path) or any(re.search(r'answer|submit|start|save|begin|doexam',key,re.I) for key,_ in parse_qsl(parsed.query)):
        return ''
    key=platform_identity(original)
    return value if key and key==platform_identity(value) else ''


def task_content_url(value):
    """Allowlisted assignment HTML GET only; never a browser navigation target."""
    from .task_identity import identity_parts
    try:value=safe_task_url(value)
    except ValidationError:return ''
    parsed=urlsplit(value)
    if not re.fullmatch(r'/(?:mooc-ans/)?(?:mooc2/)?work/(?:task|dowork|view|detail)',parsed.path):return ''
    if any(re.search(r'exam|submit|start|save|begin|answer',key,re.I) and key.lower() not in ('answerid','workanswerid') for key,_ in parse_qsl(parsed.query)):return ''
    identity=identity_parts(value)
    return value if identity['key'] and identity['kind']=='assignment' else ''


def task_payload(external,course,scope,at):
    fields=('message_id','title','url','detail_url','task_type','deadline','published_at','submission_method','platform_status','teacher','field_evidence','description','attachments','detail_state','detail_error','media_pending_count')
    return dict({key:external[key] for key in fields if key in external},kind='task_center',text=external.get('task_body',''),course=course,conversation=scope,captured_at=at)


def merge_task_attachments(previous,incoming,course,scope):
    """Add discovered files or improve text on an identical task observation."""
    from .message_capture import capture_key
    if previous.get('kind')!='task_center' or 'task_body' not in previous or 'task_body' not in incoming:return None,False
    before_key=capture_key(dict(previous,attachments=[]),course,scope,previous['task_body'])
    after_key=capture_key(dict(incoming,attachments=[]),course,scope,incoming['task_body'])
    if not before_key or before_key!=after_key:return None,False
    before,after=previous.get('attachments',[]),incoming.get('attachments',[])
    identity=lambda a:(a['name'],a['url'],a.get('size',0))
    old_files={identity(a):a for a in before};new_files={identity(a):a for a in after}
    if not old_files.keys()<=new_files.keys():return None,False
    rank={'listed':0,'failed':0,'skipped':0,'partial':1,'extracted':2};merged=[];conflict=False
    improved=len(new_files)>len(old_files) or previous.get('media_pending_count',0)!=incoming.get('media_pending_count',0)
    for key,new in new_files.items():
        old=old_files.get(key)
        if old is None:merged.append(new);continue
        incompatible=bool(old.get('text') and new.get('text') and old['text']!=new['text'] and (old['status']=='extracted' or not new['text'].startswith(old['text'])))
        conflict|=incompatible
        better=not incompatible and bool(new.get('text')) and rank[new['status']]>rank[old['status']]
        improved|=better;merged.append(new if better else old)
    return (dict(previous,attachments=merged,media_pending_count=incoming.get('media_pending_count',0)) if improved and not conflict else None),conflict


def notice_text(external):
    attachments=external['attachments']
    parts=[external['title'],external['notice_body']]
    if attachments: parts+=['附件列表：']+[item['name'] for item in attachments]
    for item in attachments:
        if item['text']: parts+=['【附件正文：'+item['name']+'】',item['text']]
    return '\n'.join(parts)


def merge_notice_attachments(previous,incoming):
    """Only improve attachment extraction for the same original notice evidence."""
    if previous.get('kind')!='course_notice' or incoming.get('kind')!='course_notice': return None
    for key in ('title','url','notice_body','sender','conversation','time_known','display_time'):
        if previous.get(key)!=incoming.get(key): return None
    before=previous.get('attachments',[]);after=incoming.get('attachments',[])
    if [(a['name'],a['url'],a['size']) for a in before]!=[(a['name'],a['url'],a['size']) for a in after[:len(before)]]: return None
    added=after[len(before):]
    if any(a.get('kind')!='inline_image' for a in added):return None
    merged=[];improved=bool(added);rank={'listed':0,'failed':0,'skipped':0,'partial':1,'extracted':2}
    for old,new in zip(before,after):
        better=bool(new['text']) and rank[new['status']]>rank[old['status']]
        if better and old['status']=='partial' and not new['text'].startswith(old['text']): better=False
        merged.append(new if better else old);improved|=better
    merged.extend(added)
    result=dict(previous,attachments=merged)
    if incoming.get('media_pending_count',0)!=previous.get('media_pending_count',0):
        result['media_pending_count']=incoming.get('media_pending_count',0);improved=True
    return result if improved and len(notice_text(result))<=30000 else None


def normalize_web_message(body):
    kind=body.get('kind','chat')
    if kind not in ('chat','course_notice','task_center','checkin_activity'): raise ValidationError('网页来源类型不支持。')
    allowed={'message_id','text','conversation','sender','display_time','captured_at','direction','kind'}
    if kind=='chat':allowed.add('activity_type')
    if kind=='course_notice': allowed|={'course','title','url','attachments','media_pending_count'}
    if kind=='task_center': allowed|={'course','title','url','detail_url','task_type','deadline','published_at','submission_method','platform_status','teacher','field_evidence','description','attachments','detail_state','detail_error','media_pending_count'}
    if kind=='checkin_activity': allowed|={'course','title','deadline','published_at','activity_id','course_id','class_id','chat_source_id','field_evidence','activity_state'}
    if set(body)-allowed: raise ValidationError('网页消息包含不支持的字段。')
    message_id=clean_string(body.get('message_id'),'网页消息编号',200,True)
    if not re.fullmatch(r'[A-Za-z0-9_-]+',message_id): raise ValidationError('网页消息编号无效。')
    text=clean_string(body.get('text'),'消息正文',30000,kind!='course_notice')
    course=clean_string(body.get('course',''),'课程',100)
    conversation=clean_string(body.get('conversation',course),'会话',100,kind=='chat')
    sender=clean_string(body.get('sender',''),'发件人',100)
    display_time=clean_string(body.get('display_time',''),'网页时间标记',100)
    direction=body.get('direction','received')
    if direction not in ('received','sent') or (kind in ('course_notice','task_center','checkin_activity') and direction!='received'): raise ValidationError('消息方向无效。')
    at=body.get('captured_at');time_known=at is not None
    at=parse_timestamp(at).isoformat() if time_known else now_iso()
    external=dict(platform='chaoxing-web',message_id=message_id,conversation=conversation,sender=sender,display_time=display_time,direction=direction,time_known=time_known)
    if 'activity_type' in body:
        if body['activity_type']!='checkin' or '签到' not in text or len(text)>160:raise ValidationError('签到卡片类型或标题无效。')
        external['activity_type']='checkin'
    if kind=='course_notice':
        title=clean_string(body.get('title'),'通知标题',160,True)
        external.update(kind=kind,title=title,url=safe_notice_url(body.get('url','')),notice_body=text)
        pending=body.get('media_pending_count',0)
        if type(pending) is not int or not 0<=pending<=1000:raise ValidationError('未读取媒体数量无效。')
        external['media_pending_count']=pending
        attachments=body.get('attachments',[])
        if not isinstance(attachments,list) or len(attachments)>20: raise ValidationError('通知最多 20 个附件。')
        safe=[]
        for attachment in attachments:
            if not isinstance(attachment,dict) or set(attachment)-{'name','url','status','text','error','size','kind'}: raise ValidationError('附件字段不支持。')
            media_kind=attachment.get('kind')
            if media_kind not in (None,'inline_image'):raise ValidationError('附件类型无效。')
            item=dict(name=clean_string(attachment.get('name'),'附件名称',180,True),url=safe_image_url(attachment.get('url','')) if media_kind else safe_attachment_url(attachment.get('url','')),status=attachment.get('status','listed'))
            if media_kind:item['kind']=media_kind
            if item['status'] not in ('listed','extracted','partial','failed','skipped'): raise ValidationError('附件读取状态无效。')
            item['text']=clean_string(attachment.get('text',''),'附件文字',20000)
            item['error']=clean_string(attachment.get('error',''),'附件说明',250)
            if item['text'] and item['status'] not in ('extracted','partial'): raise ValidationError('附件状态与文字不一致。')
            size=attachment.get('size',0)
            if isinstance(size,bool) or not isinstance(size,int) or size<0 or size>10**10: raise ValidationError('附件大小无效。')
            item['size']=size;safe.append(item)
        external['notice_body_state']='text' if text else 'attachment_only' if safe else 'media_only' if pending else 'empty'
        external['attachments']=safe
        text=notice_text(external)
        if len(text)>30000: raise ValidationError('通知与附件文字超过 30000 字，请分段导入。')
    candidates=None if time_known else []
    source=NOTICE_SOURCE if kind=='course_notice' else SOURCE
    if kind=='task_center':
        title=clean_string(body.get('title'),'任务标题',160,True)
        task_type=body.get('task_type','assignment')
        if task_type not in ('assignment','exam','experiment','project','presentation','other'): raise ValidationError('任务类型无效。')
        deadline,deadline_precision=validate_deadline(body.get('deadline'))
        published_at,_=validate_deadline(body.get('published_at'))
        submission=clean_string(body.get('submission_method',''),'提交方式',160)
        description=clean_string(body.get('description',''),'任务说明',2000)
        teacher=clean_string(body.get('teacher',sender),'教师',100)
        platform_status=clean_string(body.get('platform_status',''),'平台状态',100)
        evidence=body.get('field_evidence',{})
        if not isinstance(evidence,dict) or set(evidence)-{'title','course','deadline','published_at','submission_method'}: raise ValidationError('字段依据无效。')
        evidence={key:clean_string(value,'字段依据',240,True) for key,value in evidence.items() if value}
        if not deadline:
            from .task_window import deadline_from_window
            inferred=deadline_from_window(evidence.get('deadline',''),published_at)
            if inferred:deadline,deadline_precision=validate_deadline(inferred)
        url=safe_task_url(body.get('url',''))
        detail_url=task_detail_url(body.get('detail_url',''),url)
        if body.get('detail_url') and (not detail_url or task_type=='exam'):raise ValidationError('说明链接必须属于同一个任务的只读页面。')
        attachments=body.get('attachments',[])
        if not isinstance(attachments,list) or len(attachments)>20: raise ValidationError('任务最多 20 个附件。')
        safe=[]
        for item in attachments:
            if not isinstance(item,dict) or set(item)-{'name','url','status','text','error','size','kind'}: raise ValidationError('任务附件字段无效。')
            status=item.get('status','listed');content=clean_string(item.get('text',''),'附件文字',20000)
            if status not in ('listed','extracted','partial','failed','skipped') or content and status not in ('extracted','partial') or status=='extracted' and not content:raise ValidationError('任务附件状态与正文不一致。')
            size=item.get('size',0)
            if type(size) is not int or not 0<=size<=10**10:raise ValidationError('附件大小无效。')
            image=item.get('kind')=='inline_image'
            if item.get('kind') not in (None,'','inline_image'):raise ValidationError('任务附件类型无效。')
            attachment=dict(name=clean_string(item.get('name'),'附件名称',180,True),url=safe_image_url(item.get('url','')) if image else safe_attachment_url(item.get('url','')),status=status)
            if image:attachment['kind']='inline_image'
            for field,value in (('text',content),('error',clean_string(item.get('error',''),'附件说明',250)),('size',size)):
                if value:attachment[field]=value
            safe.append(attachment)
        detail_state=body.get('detail_state','list_only')
        if detail_state not in ('list_only','read','skipped','unavailable'): raise ValidationError('详情读取状态无效。')
        detail_error=clean_string(body.get('detail_error',''),'详情读取说明',250)
        pending=body.get('media_pending_count',0)
        if type(pending) is not int or not 0<=pending<=1000:raise ValidationError('未读取的任务媒体数量无效。')
        external.update(kind=kind,title=title,url=url,task_type=task_type,deadline=deadline,submission_method=submission,teacher=teacher,platform_status=platform_status,field_evidence=evidence,description=description,attachments=safe,detail_state=detail_state,detail_error=detail_error)
        if detail_url:external['detail_url']=detail_url
        external['task_body']=text
        for attachment in safe:
            if attachment.get('text'):text+='\n【附件正文：'+attachment['name']+'】\n'+attachment['text']
        if len(text)>30000:raise ValidationError('任务与附件文字超过30000字。')
        external['media_pending_count']=pending
        if published_at:external['published_at']=published_at
        candidate=dict(title=title,course=course,scope=conversation,deadline=deadline,date_precision=deadline_precision,kind=task_type,
                       requirements=([description] if description else [])+['附件：'+a['name'] for a in safe],operation='create',matchable=True,evidence=text[:1200],deadline_evidence=evidence.get('deadline',''),warnings=[detail_error] if detail_error else [],captured_at=at,
                       submission_method=submission,teacher=teacher,source_url=url,platform_status=platform_status,confidence='high',field_evidence=evidence)
        if pending:candidate['warnings'].append('作业说明含尚未读取的图片或媒体，请打开原任务核对。')
        for attachment in safe:
            if attachment.get('text'):candidate['requirements'].append('附件正文（'+attachment['name']+'）：'+attachment['text'])
            if attachment['status']!='extracted':candidate['warnings'].append('附件“'+attachment['name']+'”尚未完整读取，请核对原文件。')
        # Checklists have a per-item limit; retain the complete source separately.
        requirements=[line[i:i+180] for item in candidate['requirements'] for line in item.splitlines() if line.strip() for i in range(0,len(line),180)]
        if len(requirements)>30:candidate['warnings'].append('任务要求较长，清单仅列前30项，请核对完整原文。')
        candidate['requirements']=requirements[:30]
        candidates=[candidate];source=TASK_SOURCE
    elif kind=='checkin_activity':
        title=clean_string(body.get('title'),'签到活动标题',160,True)
        if '签到' not in title: raise ValidationError('签到活动标题无效。')
        activity_id=clean_string(body.get('activity_id'),'活动编号',80,True)
        if not re.fullmatch(r'[A-Za-z0-9_-]+',activity_id): raise ValidationError('签到活动编号无效。')
        course_id=clean_string(body.get('course_id'),'课程编号',80,True)
        class_id=clean_string(body.get('class_id'),'班级编号',80,True)
        if not re.fullmatch(r'[A-Za-z0-9_-]+',course_id) or not re.fullmatch(r'[A-Za-z0-9_-]+',class_id): raise ValidationError('签到活动课程或班级编号无效。')
        chat_source_id=clean_string(body.get('chat_source_id',''),'聊天来源编号',200)
        if chat_source_id and not re.fullmatch(r'[A-Za-z0-9_-]+',chat_source_id): raise ValidationError('聊天来源编号无效。')
        deadline,deadline_precision=validate_deadline(body.get('deadline'))
        published_at,_=validate_deadline(body.get('published_at'))
        activity_state=body.get('activity_state','')
        if activity_state not in ('','ended'):raise ValidationError('签到活动状态无效。')
        if not published_at or (not deadline and activity_state!='ended'): raise ValidationError('签到活动缺少明确的结束时间或发布时间。')
        evidence=body.get('field_evidence',{})
        if not isinstance(evidence,dict) or set(evidence)-{'deadline','published_at','activity_state'}: raise ValidationError('签到活动字段依据无效。')
        if activity_state=='ended' and evidence.get('activity_state') not in ('已结束','已截止','已过教师设置的截止时间'):raise ValidationError('签到结束状态缺少平台明确依据。')
        evidence={key:clean_string(value,'字段依据',240,True) for key,value in evidence.items() if value}
        external.update(kind=kind,title=title,activity_id=activity_id,course_id=course_id,class_id=class_id,
                        deadline=deadline,published_at=published_at,field_evidence=evidence)
        if chat_source_id:external['chat_source_id']=chat_source_id
        if activity_state:external['activity_state']=activity_state
        candidates=[dict(title=title,course='',scope=conversation,deadline=deadline,date_precision=deadline_precision,
                         kind='other',requirements=[],operation='update',matchable=True,evidence=text[:1200],
                         deadline_evidence=evidence.get('deadline',''),warnings=[],captured_at=at,
                         submission_method='',teacher=sender,source_url='',platform_status='',confidence='high',
                         field_evidence=evidence,deadline_change_requested=True)]
        source=TASK_SOURCE
    return dict(text=text,source=source,course=course,scope=conversation,captured_at=at,external=external,candidates=candidates)



def parse_notice_candidates(external,at,course,scope):
    # Narrative about research submissions is evidence, not a student command.
    instructions=[]
    for attachment in external.get('attachments',[]):
        lines=attachment.get('text','').splitlines()
        for index,line in enumerate(lines):
            field=bool(re.search(r'^\s*[^。！？]{0,12}(?:截止|截至|最晚|结束时间|结束日期|提交方式|提交时间|上传方式)\s*[:：]?',line))
            if field or re.search(r'(?:请|必须|需要|要求|应当|须|需)[^。！？]{0,12}(?:提交|上传|完成|阅读|预习)|^(?:[\d、.\s]*)(?:提交|上传|完成|阅读|预习)',line):
                instructions.append(line)
                if field and re.search(r'[:：]\s*$',line) and index+1<len(lines):instructions.append(lines[index+1])
    text='\n'.join([external['title'],external['notice_body']]+instructions)
    candidates=refine_notice_candidates(parse_message(text,at,course,scope),external)
    original=notice_text(external)
    for candidate in candidates:
        if candidate['evidence'] not in original: candidate['evidence']=original[:1200]
    return candidates


def refine_notice_candidates(candidates,external):
    if external.get('kind')!='course_notice': return candidates
    from .task_identity import canonical_title
    extracted=[a for a in external.get('attachments',[]) if a.get('status') in ('extracted','partial') and a.get('text')]
    for candidate in candidates:
        if len(candidates)==1 and candidate.get('operation')!='update':
            candidate['title']=canonical_title(external['title'],candidate.get('course',''))
        if extracted:
            candidate['warnings']=[warning for warning in candidate['warnings'] if '附件正文尚未导入' not in warning]
        for attachment in extracted:
            text=attachment['text']
            if re.search(r'一个人只读一篇|每人(?:只需|只)?(?:阅读|读)一篇',text):
                candidate['requirements'].append('组内分配，每人只读一篇材料')
            if re.search(r'不要求通读[^。]{0,30}只读|无需通读',text):
                candidate['requirements'].append('只读附件指定页码，无需通读全文')
            page_column=None
            for line in text.splitlines():
                cells=[re.sub(r'\s+',' ',cell).strip() for cell in line.split('|')]
                if len(cells)>2 and '材料' in cells[0] and any('只读' in cell and '页' in cell for cell in cells):
                    page_column=next(i for i,cell in enumerate(cells) if '只读' in cell and '页' in cell)
                elif page_column is not None and len(cells)>page_column and re.fullmatch(r'第[\d\s、，,及和]+页',cells[page_column]):
                    requirement=cells[0]+'：'+cells[page_column]
                    if len(requirement)<=180: candidate['requirements'].append(requirement)
            if attachment.get('status')=='partial': candidate['warnings'].append('附件“'+attachment['name']+'”只读取了部分文字，请核对原文件。')
        candidate['requirements']=list(dict.fromkeys(candidate['requirements']))[:30]
    return candidates

def absolute_candidates(message):
    """No clock/receipt fallback for missing publication or relative dates."""
    anchor='2000-01-01T00:00:00+08:00'
    if message['external'].get('kind')=='course_notice':
        parsed=parse_notice_candidates(message['external'],anchor,message['course'],message['scope'])
    else:parsed=parse_message(message['text'],anchor,message['course'],message['scope'])
    parsed=[automatic_candidate(c,dict(message,captured_at=anchor)) for c in parsed]
    from .relative_deadlines import source_text,duration_hint
    return [c for c in parsed if (c.get('deadline') and re.search(r'\d{4}\s*[年/-]\s*\d{1,2}',c.get('deadline_evidence',''))) or duration_hint(source_text(message))]


def checkin_card_candidates(message):
    """Card titles identify activities; they are not deadline instructions."""
    parsed=parse_message(message['text'],message['captured_at'],message['course'],message['scope'])
    if not parsed:return []
    return [dict(parsed[0],title=message['text'],kind='other',deadline=None,date_precision='unknown',deadline_evidence='',operation='create',deadline_change_requested=False,requirements=[])]


def ingest_web_message(inbox, body):
    from .checkin_evidence import is_checkin
    normalized = normalize_web_message(body)
    if normalized['external'].get('kind')=='checkin_activity':
        return inbox.ingest_checkin_activity(normalized)
    unknown_publication=normalized['external'].get('kind')!='task_center' and not normalized['external']['time_known']
    if unknown_publication:normalized['candidates']=absolute_candidates(normalized)
    elif is_checkin(normalized):normalized['candidates']=checkin_card_candidates(normalized)
    if normalized['external'].get('kind')=='course_notice' and normalized['external']['time_known']:
        normalized['candidates']=parse_notice_candidates(normalized['external'],normalized['captured_at'],normalized['course'],normalized['scope'])
    if normalized['candidates'] is None:
        normalized['candidates']=parse_message(normalized['text'],normalized['captured_at'],normalized['course'],normalized['scope'])
    if not unknown_publication:normalized['candidates']=[automatic_candidate(candidate,normalized) for candidate in normalized['candidates']]
    try:
        return inbox.ingest(**normalized)
    except ValidationError:
        # Validated original text must survive a task-rule validation failure.
        normalized['candidates'] = []
        normalized['external']['extraction_warning'] = '正文已保存，任务提取未成功，请人工核对后导入任务。'
        return inbox.ingest(**normalized)
