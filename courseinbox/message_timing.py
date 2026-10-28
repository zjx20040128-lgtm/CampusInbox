"""Read-only publication/deadline context for inbox presentation."""
import json
import re
from .task_identity import platform_identity,canonical_title,normalized


def source_deadline(message, published):
    """Re-read source evidence independently of whether its draft was dismissed."""
    from .core import extract_deadline,parse_timestamp,DEADLINE_CHANGE_PATTERN
    from .intake_policy import _deadline_segment,_DEADLINE_CUE
    from .task_window import deadline_from_window
    ext=message.get('external',{})
    if ext.get('kind')=='task_center':
        return deadline_from_window(ext.get('field_evidence',{}).get('deadline',''),published)
    text=message.get('text','')
    # A single record may describe several tasks. Never select its first due date
    # as the deadline of the whole record, nor override the existing ambiguity guard.
    if len(list(re.finditer(_DEADLINE_CUE+'|'+DEADLINE_CHANGE_PATTERN,text)))>1:return None
    segment=_deadline_segment(text)
    if not segment:return None
    anchor=parse_timestamp(published+'T00:00:00+08:00' if published and len(published)==10 else published or '2000-01-01T00:00:00+08:00')
    deadline,_,evidence,_=extract_deadline(segment,anchor)
    if not published and not re.search(r'\d{4}\s*[-/年]\s*\d{1,2}',evidence):return None
    return deadline


def date_key(value):
    from .core import parse_timestamp,ValidationError
    from datetime import timezone
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):value+='T00:00:00+08:00'
    try:return parse_timestamp(value).astimezone(timezone.utc).isoformat() if value else ''
    except ValidationError:return ''


def annotate(inbox,db,messages):
    from .time_evidence import publication
    tasks={task['id']:task for row in db.execute('SELECT data FROM tasks') if not (task:=json.loads(row['data'])).get('merged_into')}
    identities={};linked={};release={};candidates={}
    for task_id,task in tasks.items():
        for key in inbox._task_platform_identities(db,task):identities.setdefault(key,set()).add(task_id)
    for row in db.execute('SELECT s.task_id,m.id,m.data FROM sources s JOIN messages m ON m.id=s.message_id'):
        if row['task_id'] not in tasks:continue
        linked.setdefault(row['id'],set()).add(row['task_id'])
        message=json.loads(row['data']);ext=message.get('external',{});task=tasks[row['task_id']]
        same_title=normalized(canonical_title(ext.get('title',''),task['course']))==normalized(canonical_title(task['title'],task['course']))
        if ext.get('kind')=='course_notice' and ext.get('time_known') is True and same_title and not re.search(r'取消|延期|延后|截止改|已结束',ext.get('notice_body','')):
            release.setdefault(row['task_id'],[]).append(message['captured_at'])
    for row in db.execute("SELECT s.message_id,p.data FROM proposal_sources s JOIN proposals p ON p.id=s.proposal_id WHERE p.status IN ('pending','archived')"):
        candidate=json.loads(row['data']).get('candidate',{})
        if candidate.get('deadline') and candidate.get('deadline_evidence'):candidates.setdefault(row['message_id'],set()).add(candidate['deadline'])
    result=[]
    for message in messages:
        ext=message.get('external',{});is_task=ext.get('kind')=='task_center'
        published=publication(message,db)
        publication_source='platform' if is_task and published else 'message' if published else 'unknown'
        deadline=ext.get('deadline');deadline_source='message' if deadline else 'unknown'
        if not deadline:
            deadline=source_deadline(message,published)
            if deadline:deadline_source='message'
        if not deadline:
            from .checkin_evidence import references as checkin_references,unique as unique_checkin
            refs=checkin_references(db,message)
            if unique_checkin(refs):deadline=refs[0]['deadline'];deadline_source='message'
        key=platform_identity(ext.get('url','')) if is_task else ''
        owners=identities.get(key,set()) if is_task else linked.get(message['id'],set())
        if len(owners)==1:
            task_id=next(iter(owners));task=tasks[task_id]
            if not published and is_task and release.get(task_id):published=min(release[task_id],key=date_key);publication_source='notice'
            if not deadline and task.get('deadline'):deadline=task['deadline'];deadline_source='confirmed_task'
        if not deadline and len(candidates.get(message['id'],set()))==1:deadline=next(iter(candidates[message['id']]));deadline_source='candidate'
        result.append(dict(message,timing=dict(published_at=published,publication_source=publication_source,deadline=deadline,deadline_source=deadline_source)))
    return result
