"""Bounded relative extensions, resolved against confirmed tasks inside a transaction."""
import hashlib
import json
import re
from datetime import timedelta


def source_text(message):
    external=message.get('external',{})
    if external.get('kind')=='course_notice':return external.get('notice_body') or external.get('title') or message['text']
    return message['text']


def duration_hint(text):
    return bool(re.search(r'(?:延期|延长|推迟|顺延|延后|再延)\s*(?:\d+|[一二三四五六七八九十两]+)\s*(?:天|日|周|小时|分钟)',text))


def request(text):
    """Only a standalone affirmative duration instruction; no inferred intent."""
    raw=re.sub(r'^\s*《[^》]{1,80}》\s*','',text).strip()
    if re.search(r'[？?]|不要|无需|不用|不再|不必|不得|不能|不延期|不延|未|如果|假如|假设|若|申请|建议|希望|能否|是否|可否|可以|计划|争取|可能|例如|比如',raw):return None
    match=re.fullmatch(r'(?P<subject>[^。；;，,\n！？!]{0,100}?)\s*(?:的)?(?:截止(?:时间|日期)?\s*)?(?:再\s*)?(?:延期|延长|推迟|顺延|延后|延)\s*(?P<count>\d{1,3}|[一二三四五六七八九十两]{1,3})\s*(?P<unit>天|日|周|小时|分钟)(?:[。！!]|[，,]\s*请按时提交[。！!]?)?',raw)
    if not match:return None
    value=match['count'];digits={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if value.isdigit():number=int(value)
    elif value=='十':number=10
    elif value in digits:number=digits[value]
    elif value.count('十')==1:
        left,right=value.split('十');number=digits.get(left,1 if not left else 0)*10+digits.get(right,0)
    else:return None
    minutes=number*{'天':1440,'日':1440,'周':10080,'小时':60,'分钟':1}[match['unit']]
    if not 0<minutes<=366*1440:return None
    subject=re.sub(r'^(?:上一次|上一份|上次|上回|之前的|原来的|原来|该|这份|本次|这次|此次)','',match['subject'].strip()).strip('的 ')
    if re.search(r'今天|明天|后天|从|之后|以上|全部|所有|各组|一组|二组|[与和及、]',subject):return None
    return dict(subject=subject,minutes=minutes,unit=match['unit'],expression=text.strip())


def resolve(inbox,db,candidate,message):
    from .core import normalize,parse_timestamp,validate_deadline,parse_message,extract_deadline
    from .task_identity import canonical_title,platform_identity
    from .time_evidence import publication,task_publication,key
    c=dict(candidate);c.pop('relative_deadline',None)
    body=source_text(message)
    parts=parse_message(body,message['captured_at'],c.get('course',''),c.get('scope','')) if duration_hint(body) else []
    if len(parts)>1:
        same=[p for p in parts if normalize(canonical_title(p['title'],p.get('course','')))==normalize(canonical_title(c.get('title',''),c.get('course','')))]
        if len(same)==1:body=same[0]['evidence']
    spec=request(body)
    if message.get('external',{}).get('kind')=='task_center' and c.get('deadline'):return c
    if not spec:
        if duration_hint(body):
            from .intake_policy import _deadline_segment
            segment=_deadline_segment(body)
            if segment and not re.search(r'不要|不用|不必|不延期|如果|若|能否|是否|申请|建议|[？?]',body):
                due,precision,evidence,warnings=extract_deadline(segment,parse_timestamp(message['captured_at']))
                if due and evidence in body and re.search(r'\d{4}\s*[年/-]\s*\d{1,2}',evidence):
                    c.update(operation='update',deadline_change_requested=True,deadline=due,date_precision=precision,deadline_evidence=evidence)
                    c['warnings']=[w for w in c.get('warnings',[]) if '未识别到明确截止' not in w]+warnings
                    return c
            c.update(operation='update',deadline_change_requested=True,deadline=None,date_precision='unknown',deadline_evidence='',
                relative_deadline=dict(status='unresolved',expression=body,options=[]))
            c['warnings']=list(c.get('warnings',[]))+['相对延期含附加内容或条件，尚未计算；请核对原任务与明确截止时间。']
        return c
    c.update(operation='update',deadline_change_requested=True,deadline=None,date_precision='unknown',deadline_evidence='',requirements=[],matchable=False)
    c['warnings']=[w for w in c.get('warnings',[]) if not any(t in w for t in ('未识别到明确截止','任务名称较笼统'))]
    published=publication(message,db)
    binding=dict(status='unresolved',expression=spec['expression'],delta_minutes=spec['minutes'],source_published_at=published,options=[])
    c['relative_deadline']=binding
    def unresolved(reason):
        c['warnings'].append(reason);return c
    if not c.get('course') or not spec['subject']:return unresolved('延期任务或课程未明确，请核对原任务。')
    if spec['expression'] not in message['text']:return unresolved('延期依据未能在原文中核实，请核对通知。')
    if message.get('external',{}).get('attachments') or message.get('external',{}).get('media_pending_count'):
        return unresolved('延期通知含附件或未读取内容，请核对完整通知后填写截止时间。')
    hint=normalize(canonical_title(spec['subject'],c['course']))
    matches=[]
    for row in db.execute('SELECT data FROM tasks ORDER BY rowid'):
        task=json.loads(row['data'])
        if task.get('merged_into') or task.get('excluded_reason') or task.get('status') in ('done','submitted','cancelled'):continue
        if normalize(task['course'])!=normalize(c['course']) or normalize(task.get('scope',''))!=normalize(c.get('scope','')):continue
        identities=inbox._task_platform_identities(db,task)
        if not inbox._compatible_identities(c,identities) or len(identities)>1:continue
        incoming=platform_identity(c.get('source_url',''))
        if incoming and identities and incoming not in identities:continue
        title=normalize(canonical_title(task['title'],task['course']))
        generic=hint in ('报告','作业','任务')
        report='报告' in task['title'] or any('报告' in item['text'] for item in task.get('checklist',[]))
        if title==hint or generic and (report if hint=='报告' else task['kind']!='exam'):
            matches.append(task)
    binding['options']=[dict(task_id=t['id'],title=t['title'],deadline=t['deadline'],version=t['version']) for t in matches[:20]]
    if len(matches)!=1:
        binding['status']='ambiguous' if matches else 'unresolved'
        return unresolved('存在多个可能的原任务，请核对任务名称后重新提取。' if matches else '未找到同课程、同班级的原任务，请核对后重新提取。')
    task=matches[0]
    if not published:return unresolved('通知发布时间未获取，无法核对延期顺序；请补充真实发布时间。')
    event_key=hashlib.sha256(json.dumps([task['id'],published,spec['minutes']],ensure_ascii=False).encode()).hexdigest()
    binding.update(task_id=task['id'],event_key=event_key,base_version=task['version'],base_deadline=task['deadline'],base_message_id=task.get('deadline_basis',{}).get('message_id'))
    applied=any(item.get('key')==event_key for item in task.get('relative_deadline_applied',[]))
    if not applied:
        latest=task_publication(db,task,latest=True)
        if key(latest) and key(published)<=key(latest):return unresolved('通知未明确晚于原任务最新来源，不能自动累加延期，请核对发布时间。')
        if not task['deadline']:return unresolved('原任务尚未公布或未确认截止时间，无法计算延期后的日期。')
        if len(task['deadline'])==10 and spec['unit'] not in ('天','日','周'):return unresolved('原截止只有日期，无法推算按小时或分钟延期后的时刻。')
        base=task['deadline']+'T00:00:00+08:00' if len(task['deadline'])==10 else task['deadline']
        try:due=parse_timestamp(base)+timedelta(minutes=spec['minutes'])
        except OverflowError:return unresolved('延期结果超出日期范围，请人工核对。')
        deadline=due.date().isoformat() if len(task['deadline'])==10 else due.isoformat()
    else:deadline=task['deadline']
    binding.update(status='already_applied' if applied else 'resolved',deadline=deadline)
    c.update(title=task['title'],course=task['course'],scope=task.get('scope',''),kind=task['kind'],source_url=task.get('source_url',''),
             submission_method='',teacher='',field_evidence={},platform_status='',matchable=True,deadline=deadline,date_precision=validate_deadline(deadline)[1],
             operation='create' if applied else 'update',deadline_change_requested=not applied,deadline_evidence=spec['expression'])
    c['warnings'].append('该延期通知已确认过，仅关联原文，不再重复累加。' if applied else '已按原任务截止计算延期日期，请核对原截止、延期量和新截止后确认。')
    return c


def record(task,candidate,message,published_at):
    binding=candidate.get('relative_deadline',{})
    if binding.get('status')!='resolved' or not candidate.get('deadline'):return
    receipt=dict(key=binding['event_key'],deadline=candidate['deadline'],message_id=message['id'])
    applied=list(task.get('relative_deadline_applied',[]))
    if not any(item.get('key')==receipt['key'] for item in applied):applied.append(receipt)
    task['relative_deadline_applied']=applied
    task['deadline_basis']=dict(kind='relative_extension',message_id=message['id'],deadline=candidate['deadline'],published_at=published_at,
        evidence=binding['expression'],base_deadline=binding['base_deadline'],base_version=binding['base_version'],base_message_id=binding.get('base_message_id'),delta_minutes=binding['delta_minutes'])
