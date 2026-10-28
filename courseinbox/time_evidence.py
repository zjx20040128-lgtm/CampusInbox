"""Publication and deadline evidence, never receipt/scan timestamps."""
import json
import re
from .task_identity import normalized,canonical_title,platform_identity


def publication(message,db=None):
    if message.get('chat_import'):return message['chat_import'].get('published_at') or None
    ext=message.get('external',{})
    if ext.get('kind')=='task_center':return ext.get('published_at') or None
    if ext.get('time_known') is False:return None
    if ext.get('platform')=='chaoxing-web':return message.get('captured_at') if ext.get('time_known') is not False else None
    if 'reference_known' in message.get('supplement',{}):return message.get('captured_at') if message['supplement']['reference_known'] else None
    if message.get('supplement') and db is not None:
        row=db.execute('SELECT data FROM messages WHERE id=?',(message['supplement']['original_message_id'],)).fetchone()
        original=json.loads(row['data']) if row else {}
        if message.get('captured_at')==original.get('captured_at'):return publication(original,db)
    if message.get('source','').startswith('人工核对'):return None
    return message.get('captured_at') or None


def key(value):
    from .core import parse_timestamp,ValidationError
    if not value:return None
    try:return parse_timestamp(value+'T00:00:00+08:00' if len(value)==10 else value)
    except ValidationError:return None


def source_messages(db,task):
    return [json.loads(r['data']) for r in db.execute('SELECT m.data FROM sources s JOIN messages m ON m.id=s.message_id WHERE s.task_id=?',(task['id'],))]


def task_publication(db,task,latest=False):
    from .core import DEADLINE_CHANGE_PATTERN
    messages=source_messages(db,task)
    if not latest:
        from .relative_deadlines import duration_hint,source_text
        platform=[m for m in messages if m.get('external',{}).get('platform')=='chaoxing-web']
        if platform:messages=platform
        messages=[m for m in messages if not re.search(DEADLINE_CHANGE_PATTERN+r'|取消|撤销',m.get('external',{}).get('notice_body','')) and not duration_hint(source_text(m))]
    values=[publication(m,db) for m in messages];values=[v for v in values if key(v) is not None]
    if latest and key(task.get('last_published_at')) is not None:values.append(task['last_published_at'])
    return (max(values,key=key) if latest else min(values,key=key)) if values else None


def older(db,message,task,candidate=None):
    incoming=(candidate or {}).get('deadline_basis',{}).get('published_at') or publication(message,db)
    current=task_publication(db,task,latest=True)
    left,right=key(incoming),key(current)
    if left is None or right is None:return False
    if (len(incoming)==10 or len(current)==10) and left.date()==right.date():return False
    return left<right


def newer(db,left,right):
    a,b=key(publication(left,db)),key(publication(right,db))
    return a is not None and (b is None or a>b)


def fragment_conflicts(evidence,deadline):
    fragment=re.search(r'(?:至|截止|结束)[^\d]{0,8}(\d{1,2})[-月/.](\d{1,2})(?:日)?(?:\s+(\d{1,2})[:：](\d{2}))?',evidence)
    if not fragment:return False
    stamp=key(deadline)
    if stamp is None:return True
    return (int(fragment[1]),int(fragment[2]))!=(stamp.month,stamp.day) or bool(fragment[3] and len(deadline)>10 and (int(fragment[3]),int(fragment[4]))!=(stamp.hour,stamp.minute))


def same_name(subject,other):
    return bool(subject.get('course') and subject.get('title') and normalized(subject['course'])==normalized(other.get('course','')) and normalized(subject.get('scope',''))==normalized(other.get('scope','')) and normalized(canonical_title(subject['title'],subject['course']))==normalized(canonical_title(other.get('title',''),subject['course'])))


def references(db,subject,exclude_message=None):
    from .core import validate_deadline,ValidationError
    if not subject.get('course') or not subject.get('title'):return []
    own=platform_identity(subject.get('source_url',''));identities={own} if own else set();tasks=0
    for row in db.execute('SELECT data FROM tasks'):
        task=json.loads(row['data'])
        if task.get('merged_into') or task.get('excluded_reason') or not same_name(subject,task):continue
        tasks+=1
        ids=[platform_identity(task.get('source_url',''))]+[r[0] for r in db.execute('SELECT identity FROM task_identities WHERE task_id=?',(task['id'],))]
        identities.update(i for i in ids if i)
    for row in db.execute('SELECT data FROM messages WHERE hidden_at IS NULL'):
        m=json.loads(row['data']);e=m.get('external',{})
        if e.get('kind')=='task_center' and same_name(subject,dict(title=e.get('title',''),course=m.get('course',''),scope=m.get('scope',''))):
            identity=platform_identity(e.get('url',''))
            if identity:identities.add(identity)
    result=[];seen=set()
    for row in db.execute('SELECT p.data AS proposal,p.status,p.task_id,m.id,m.data AS message FROM proposals p JOIN proposal_sources s ON s.proposal_id=p.id JOIN messages m ON m.id=s.message_id WHERE m.hidden_at IS NULL ORDER BY p.rowid DESC'):
        if row['id']==exclude_message:continue
        message=json.loads(row['message']);ext=message.get('external',{})
        if ext.get('kind') not in ('course_notice','task_center'):continue
        candidate=json.loads(row['proposal']).get('candidate',{})
        identity=platform_identity(candidate.get('source_url','') or ext.get('url',''))
        if own and identity and own!=identity:continue
        stable=bool(own and identity==own)
        if (not stable and not same_name(subject,candidate)) or candidate.get('operation')=='cancel':continue
        evidence=candidate.get('deadline_evidence','')
        structured=ext.get('kind')=='task_center' and ext.get('deadline')==candidate.get('deadline') and bool(identity)
        if not structured and (not evidence or evidence not in message.get('text','') or not re.search(r'\d{4}\s*[年/-]\s*\d{1,2}',evidence)):continue
        try:deadline,_=validate_deadline(candidate.get('deadline'))
        except ValidationError:continue
        if not structured:
            from .intake_policy import _deadline_segment
            from .core import extract_deadline,parse_timestamp
            segment=_deadline_segment(message.get('text',''))
            published=publication(message,db)
            anchor=parse_timestamp(published+'T00:00:00+08:00' if published and len(published)==10 else published or '2000-01-01T00:00:00+08:00')
            if not segment or extract_deadline(segment,anchor)[0]!=deadline:continue
        marker=(row['id'],deadline)
        if not deadline or marker in seen:continue
        seen.add(marker)
        renamed=False
        if row['status']=='confirmed' and row['task_id']:
            owner=db.execute('SELECT data FROM tasks WHERE id=?',(row['task_id'],)).fetchone()
            renamed=bool(owner and not same_name(subject,json.loads(owner['data'])))
        result.append(dict(message_id=row['id'],deadline=deadline,evidence=evidence or deadline,status=row['status'],published_at=publication(message,db),kind=ext['kind'],ambiguous=not stable and (renamed or len(identities)>1 or tasks>1)))
    result.sort(key=lambda r:(key(r['published_at']) is not None,str(key(r['published_at']) or '')),reverse=True)
    return result


def proposal_view(inbox,db,proposal):
    from .core import validate_deadline
    p=dict(proposal);c=dict(p['candidate']);p['candidate']=c
    if p.get('status')=='pending':c.pop('deadline_basis',None)
    row=db.execute('SELECT data FROM messages WHERE id=?',(p['message_id'],)).fetchone()
    if not row:return p
    message=json.loads(row['data']);c['published_at']=publication(message,db)
    p['supplement_update']=bool(message.get('supplement') and p.get('target_id'))
    if p.get('status')=='pending' and not p.get('target_id') and c.get('operation','create')=='create':
        from .checkin_evidence import references as checkin_references,unique as unique_checkin
        from .core import now_iso
        refs=checkin_references(db,message)
        from .checkin_evidence import is_checkin,verification
        if is_checkin(message,db):
            state=verification(db,message)
            p['checkin_unverified']=state=='unverified'
            p['checkin_ambiguous']=state=='ambiguous'
            p['checkin_expired']=state=='ended'
        if refs:
            if unique_checkin(refs) and not p.get('checkin_ambiguous') and not c.get('deadline'):
                chosen=refs[0];c['deadline'],c['date_precision']=validate_deadline(chosen['deadline'])
                c['deadline_evidence']=chosen['evidence'];c['deadline_basis']={k:chosen[k] for k in ('message_id','deadline','published_at','kind','evidence')}
                c['warnings']=[w for w in c.get('warnings',[]) if '未识别到明确截止' not in w]+['截止来自同一场签到活动详情，请核对。']
    if p.get('status')=='pending':
        # Other messages may have created/merged a task since this draft was saved.
        p['duplicate_review']=inbox._duplicate_review(db,c)
        checkin_target=inbox._checkin_target(db,p,message,c)
        if checkin_target:p['duplicate_review']=[item for item in p['duplicate_review'] if item['task_id']!=checkin_target['id']]
    if p.get('status')=='pending' and not p.get('manual_review') and message.get('external',{}).get('kind')=='course_notice' and c.get('deadline'):
        from .date_roles import matches_non_deadline
        from .core import parse_timestamp
        published=publication(message,db)
        anchor=parse_timestamp(published+'T00:00:00+08:00' if published and len(published)==10 else published or '2000-01-01T00:00:00+08:00')
        if matches_non_deadline(message.get('text',''),c['deadline'],anchor):
            from .intake_policy import automatic_candidate
            c=automatic_candidate(c,message);p['candidate']=c
    if c.get('relative_deadline'):
        p['deadline_references']=[]
        return p
    refs=references(db,c,p['message_id']);p['deadline_references']=[r for r in refs if r['deadline']!=c.get('deadline')]
    eligible=[r for r in refs if r['status'] in ('pending','confirmed') and not r['ambiguous']]
    if p.get('status')=='pending' and not c.get('deadline') and not p.get('manual_review') and not message.get('last_analyzed_at') and message.get('external',{}).get('kind') in ('task_center','course_notice') and len({r['deadline'] for r in eligible})==1 and not fragment_conflicts(c.get('field_evidence',{}).get('deadline',''),eligible[0]['deadline']):
        chosen=eligible[0];c['deadline'],c['date_precision']=validate_deadline(chosen['deadline'])
        c['deadline_evidence']=chosen['evidence'];c['deadline_basis']={k:chosen[k] for k in ('message_id','deadline','published_at','kind','evidence')}
        c['field_evidence']={**c.get('field_evidence',{}),'deadline':chosen['evidence'][:240]}
        if chosen['kind']=='course_notice':c['confidence']='medium'
        c['warnings']=[w for w in c.get('warnings',[]) if not any(s in w for s in ('未识别到明确截止','截止时间请核对','未包含完整年份'))]+['截止依据来自关联来源，请核对后确认。']
        if not c['published_at']:c['published_at']=chosen['published_at']
        ids=list(dict.fromkeys(p.get('source_message_ids',[p['message_id']])+[chosen['message_id']]))
        p.update(source_message_ids=ids,source_count=len(ids))
        if p.get('target_id'):
            task=inbox._task(db,p['target_id']);p['action']='update' if c.get('operation')=='update' else inbox._effective_action(task,c)
            if p['action']=='conflict':p['conflicts']={k:dict(current=task[k],incoming=c[k]) for k in ('deadline','submission_method','kind') if c.get(k) and task.get(k) and c[k]!=task[k]}
    elif p.get('status')=='pending' and not c.get('deadline') and eligible and (len({r['deadline'] for r in eligible})>1 or fragment_conflicts(c.get('field_evidence',{}).get('deadline',''),eligible[0]['deadline'])):
        c['warnings']=list(c.get('warnings',[]))+['多个来源的截止时间不一致，请核对原文后填写。']
    return p
