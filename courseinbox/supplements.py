"""User-supplied evidence tied to an original message; task writes still require confirmation."""
import hashlib
import json
import re
import uuid

from .core import (Conflict,NotFound,ValidationError,clean_string,dump,now_iso,
                   parse_timestamp,parse_message,extract_deadline,DEADLINE_CHANGE_PATTERN)


def _original(db,message_id):
    row=db.execute('SELECT data FROM messages WHERE id=?',(message_id,)).fetchone()
    if not row:raise NotFound('原消息不存在或已清理。')
    message=json.loads(row['data'])
    if message.get('supplement'):raise ValidationError('请回到原消息继续补充，不能嵌套补充记录。')
    if db.execute('SELECT 1 FROM cleared_messages WHERE message_id=?',(message_id,)).fetchone():raise Conflict('原消息已清理，请先核对任务来源。')
    return message


def _targets(inbox,db,original):
    targets={}
    for row in db.execute('SELECT t.data FROM tasks t JOIN sources s ON s.task_id=t.id WHERE s.message_id=?',(original['id'],)):
        task=json.loads(row['data']);targets['task:'+task['id']]=task
    for row in db.execute('SELECT DISTINCT p.* FROM proposals p JOIN proposal_sources s ON s.proposal_id=p.id WHERE s.message_id=? ORDER BY p.rowid DESC',(original['id'],)):
        proposal=inbox._unpack_proposal(row)
        if proposal.get('task_id') or proposal.get('target_id') in {task['id'] for task in targets.values() if 'id' in task}:continue
        # Show the latest candidate for a given task, including explicitly ignored/archived ones.
        candidate=proposal['candidate']
        if any(all(candidate.get(k)==value.get(k) for k in ('course','scope','title','source_url')) for value in targets.values()):continue
        targets['proposal:'+proposal['id']]=candidate
    if not targets and original.get('external',{}).get('kind')=='task_center':
        from .chaoxing import normalize_web_message,task_payload
        payload=task_payload(original['external'],original['course'],original['scope'],original['captured_at'])
        if not payload['text']:payload['text']=original['text']
        candidates=normalize_web_message(payload)['candidates']
        if candidates:targets['source']=candidates[0]
    return targets


def _resolve(inbox,db,original,key):
    targets=_targets(inbox,db,original)
    if key=='auto':return None
    if key in targets:return targets[key]
    # An idempotent retry can still name a draft that the first request replaced.
    if isinstance(key,str) and key.startswith('proposal:'):
        row=db.execute('SELECT p.* FROM proposals p JOIN proposal_sources s ON s.proposal_id=p.id WHERE p.id=? AND s.message_id=?',(key[9:],original['id'])).fetchone()
        if row:
            proposal=inbox._unpack_proposal(row)
            if proposal.get('task_id'):return inbox._task(db,proposal['task_id'])
            return proposal['candidate']
    raise ValidationError('补充目标不属于这条原消息，请重新选择。')


def context(inbox,db,message_id):
    from .time_evidence import publication
    original=_original(db,message_id)
    targets=_targets(inbox,db,original)
    records=[]
    for row in db.execute('SELECT m.data,s.created_at FROM message_supplements s JOIN messages m ON m.id=s.message_id WHERE s.original_message_id=? ORDER BY s.created_at DESC,s.rowid DESC',(message_id,)):
        message=json.loads(row['data']);states={r[0] for r in db.execute('SELECT p.status FROM proposals p JOIN proposal_sources ps ON ps.proposal_id=p.id WHERE ps.message_id=?',(message['id'],))}
        status='pending' if 'pending' in states else 'confirmed' if 'confirmed' in states else 'dismissed' if states else 'unrecognized'
        records.append(dict(id=message['id'],text=message['text'],created_at=row['created_at'],status=status,filename=message['supplement'].get('filename',''),file_partial=message['supplement'].get('file_partial',False)))
    published=publication(original,db)
    return dict(original_message_id=message_id,reference_at=published,reference_known=bool(published),targets=[dict(key=key,**{name:value.get(name,'') for name in ('title','course','scope','kind')}) for key,value in targets.items()],records=records)


def _preserve_requirements(text,requirements,anchor):
    """Keep explicit supplementary prose that the material parser cannot express."""
    result=list(requirements)
    def key(value):
        return re.sub(r'^(?:(?:请|需要|需|同时|另外|还|一并|提交|上传|附带|附加|附|上交|包含|包括|提供)\s*)+','',value).strip(' \t：:。；;')
    for part in re.split(r'[\n。；;]+',text):
        part=part.strip()
        if not part or re.fullmatch(r'(?:其他|其余|其它)(?:要求|内容)?不变[，,\s]*',part):continue
        if re.match(r'^(?:提交方式|提交时间|发布时间|开始时间|结束时间|任务名称|课程名称)\s*[:：]',part):continue
        due=extract_deadline(part,anchor)[0]
        if due and not re.search(r'使用|采用|编写|附|格式|字数|禁止|不得|不能|源代码|截图|报告|提交(?!时间|截止)',part):continue
        if any(key(part)==key(value) for value in result):continue
        result.extend(part[i:i+180] for i in range(0,len(part),180))
    if len(result)>30:raise ValidationError('补充后的任务要求超过30项，请精简后再生成草稿；原任务不会修改。')
    return list(dict.fromkeys(result))


def candidates_for(inbox,db,message):
    from .time_evidence import publication
    meta=message['supplement'];original=_original(db,meta['original_message_id'])
    baseline=_resolve(inbox,db,original,meta['target'])
    published=publication(message,db)
    analysis_at=(published+'T00:00:00+08:00' if len(published or '')==10 else published) or '2000-01-01T00:00:00+08:00'
    parsed=parse_message(message['text'],analysis_at,message['course'],message['scope'])
    if baseline is None:
        candidates=parsed
        for candidate in candidates:
            if not published and candidate.get('deadline') and not re.search(r'\d{4}\s*[-/年]\s*\d{1,2}',candidate.get('deadline_evidence','')):
                candidate.update(deadline=None,date_precision='unknown')
                candidate.setdefault('warnings',[]).append('发布时间未知，无法推算相对日期或年份，请核对截止时间。')
    else:
        # Keep the selected task identity; free-form attachment titles cannot redirect the update.
        target=inbox._task(db,baseline['id']) if baseline.get('id') else inbox._match(db,baseline)
        baseline=target or baseline
        candidate={name:baseline.get(name,default) for name,default in (('title',''),('course',''),('scope',''),('kind','other'),('deadline',None),('date_precision','unknown'),('submission_method',''),('teacher',''),('source_url',''),('platform_status',''),('warnings',[]))}
        previous=[item['text'] for item in baseline.get('checklist',[])] if target else baseline.get('requirements',[])
        requirements=list(previous)
        for item in parsed:requirements.extend(item['requirements'])
        # Reuse the rule parser's material extraction even if the pasted text has no task heading.
        if not parsed:
            probe=parse_message('任务名称：'+candidate['title']+'\n'+message['text'],analysis_at,candidate['course'],candidate['scope'])
            for item in probe:requirements.extend(item['requirements'])
        candidate['requirements']=_preserve_requirements(message['text'],list(dict.fromkeys(requirements)),parse_timestamp(analysis_at))
        deadline,precision,evidence,warnings=extract_deadline(message['text'],parse_timestamp(analysis_at))
        if not published:
            warnings=[w for w in warnings if not w.startswith('截止日期早于消息发布时间')]
            if deadline and not re.search(r'\d{4}\s*[-/年]\s*\d{1,2}',evidence):
                candidate.update(deadline=None,date_precision='unknown')
                deadline,precision=None,'unknown'
                warnings=['发布时间未知，无法推算相对日期或年份，请核对截止时间。']
        if deadline:candidate.update(deadline=deadline,date_precision=precision)
        if not deadline and re.search(DEADLINE_CHANGE_PATTERN,message['text']):candidate.update(deadline=None,date_precision='unknown')
        candidate.update(operation='update' if re.search(DEADLINE_CHANGE_PATTERN,message['text']) else 'create',deadline_change_requested=bool(re.search(DEADLINE_CHANGE_PATTERN,message['text'])),deadline_evidence=evidence,evidence=message['text'],matchable=True,confidence='medium')
        candidate['warnings']=list(candidate['warnings'])+[w for w in warnings if deadline or not candidate['deadline']]
        methods=[item['submission_method'] for item in parsed if item.get('submission_method')]
        if methods:candidate['submission_method']='；'.join(dict.fromkeys(methods))[:160]
        candidates=[candidate]
        if target:
            matches=inbox._matching_tasks(db,candidate)
            if len(matches)!=1 or matches[0]['id']!=target['id']:raise Conflict('目标任务存在同名或身份冲突，请先核对已有任务。')
    for candidate in candidates:
        candidate.setdefault('warnings',[]).append('此内容由用户补充，请核对原通知后再确认。')
        if meta.get('file_partial'):candidate['warnings'].append('补充文件仅读取部分文字，仍需核对原文件。')
    return candidates


def retain_original(inbox,db,proposal,original_id):
    db.execute('INSERT OR IGNORE INTO proposal_sources VALUES(?,?)',(proposal['id'],original_id))
    proposal['source_message_ids']=inbox._proposal_source_ids(db,proposal['id'])
    proposal['source_count']=len(proposal['source_message_ids'])
    db.execute('UPDATE proposals SET data=? WHERE id=?',(dump(proposal),proposal['id']))


def inventory_status(db):
    """Report manual evidence separately from automatic detail/media coverage."""
    result={}
    rows=db.execute('''SELECT s.original_message_id,s.message_id,m.data,GROUP_CONCAT(DISTINCT p.status) AS states
        FROM message_supplements s JOIN messages m ON m.id=s.message_id
        LEFT JOIN proposal_sources ps ON ps.message_id=s.message_id LEFT JOIN proposals p ON p.id=ps.proposal_id
        GROUP BY s.message_id ORDER BY s.created_at DESC,s.rowid DESC''')
    for row in rows:
        original=row['original_message_id']
        if original in result:
            result[original]['count']+=1;continue
        states=set((row['states'] or '').split(','));meta=json.loads(row['data'])['supplement']
        result[original]=dict(count=1,status='pending' if 'pending' in states else 'confirmed' if 'confirmed' in states else 'dismissed' if row['states'] else 'unrecognized',file_partial=meta.get('file_partial',False))
    return result


def submit(inbox,db,message_id,body):
    from .time_evidence import publication
    if not isinstance(body,dict) or set(body)-{'text','target','reference_at','filename','file_partial'}:raise ValidationError('补充字段不支持。')
    text=clean_string(body.get('text',''),'补充正文',20000,True)
    filename=clean_string(body.get('filename',''),'补充文件名',200)
    partial=body.get('file_partial',False)
    if type(partial) is not bool:raise ValidationError('文件读取状态无效。')
    original=_original(db,message_id);targets=_targets(inbox,db,original)
    key=clean_string(body.get('target',''),'补充目标',100,True)
    reference=body.get('reference_at') or publication(original,db)
    at=parse_timestamp(reference+'T00:00:00+08:00' if len(reference or '')==10 else reference or original['captured_at']).replace(microsecond=0).isoformat()
    fingerprint=hashlib.sha256(dump(['supplement',message_id,key,text,at,filename,partial,bool(reference)]).encode()).hexdigest()
    old=db.execute('SELECT data FROM messages WHERE fingerprint=?',(fingerprint,)).fetchone()
    if old:
        message=json.loads(old['data'])
        proposals=[inbox._unpack_proposal(r) for r in db.execute("SELECT DISTINCT p.* FROM proposals p JOIN proposal_sources ps ON ps.proposal_id=p.id WHERE ps.message_id=? AND p.status='pending'",(message['id'],))]
        return dict(message=message,proposals=proposals,duplicate=True)
    if key=='auto' and targets:raise ValidationError('请选择原消息中的任务，不能另建无关联的补充目标。')
    _resolve(inbox,db,original,key)
    created=now_iso()
    message=dict(id=uuid.uuid4().hex,text=text,source='用户补充',course=original['course'],scope=original['scope'],captured_at=at,received_at=created,sample=original.get('sample',False),mode='rules',trace=[],supplement=dict(original_message_id=message_id,target=key,filename=filename,file_partial=partial,added_at=created,reference_known=bool(reference)))
    candidates=candidates_for(inbox,db,message)
    db.execute('INSERT INTO messages(id,fingerprint,data,sort_at) VALUES(?,?,?,?)',(message['id'],fingerprint,dump(message),inbox._message_time(message)))
    db.execute('INSERT INTO message_supplements VALUES(?,?,?)',(message_id,message['id'],created))
    previous=[]
    if key.startswith('proposal:'):
        row=db.execute("SELECT * FROM proposals WHERE id=? AND status='pending'",(key[9:],)).fetchone()
        if row:
            previous.append(inbox._unpack_proposal(row));db.execute("UPDATE proposals SET status='dismissed' WHERE id=?",(key[9:],))
    proposals=[inbox._proposal(db,c,message,automatic=False) for c in candidates]
    for proposal in proposals:
        retain_original(inbox,db,proposal,message_id)
        for old in previous:inbox._retain_proposal_sources(db,proposal,old)
    return dict(message=message,proposals=proposals,duplicate=False)
