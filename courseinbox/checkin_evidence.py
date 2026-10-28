"""Bind sign-in details to one chat card, never merely the same title."""
import json
import re
from .task_identity import normalized


def origin(db,message):
    source_id=message.get('supplement',{}).get('original_message_id')
    if db is not None and source_id:
        row=db.execute('SELECT data FROM messages WHERE id=?',(source_id,)).fetchone()
        if row:return json.loads(row['data'])
    return message


def is_checkin(message,db=None):
    message=origin(db,message)
    e=message.get('external',{})
    return (e.get('platform')=='chaoxing-web' and e.get('kind','chat')=='chat'
            and e.get('direction','received')=='received'
            and (e.get('activity_type')=='checkin' or bool(re.fullmatch(r'[^\r\n。！？]{0,154}签到',message.get('text','').strip()))))


def observations(db,message):
    from .time_evidence import key,publication
    message=origin(db,message)
    ext=message.get('external',{})
    if ext.get('platform')!='chaoxing-web' or ext.get('kind','chat')!='chat' or ext.get('direction','received')!='received':return []
    posted=key(publication(message,db))
    if posted is None:return []
    result=[]
    for row in db.execute('SELECT data FROM messages WHERE hidden_at IS NULL'):
        source=json.loads(row['data']);e=source.get('external',{})
        if e.get('kind')!='checkin_activity' or e.get('chat_source_id')!=message['id']:continue
        if e.get('conversation')!=message.get('scope') or normalized(e.get('title',''))!=normalized(message.get('text','')):continue
        if not all(e.get(k) for k in ('activity_id','course_id','class_id')):continue
        published,end=key(e.get('published_at')),key(e.get('deadline'))
        if not published or (end and end<=published) or (not end and e.get('activity_state')!='ended') or abs((published-posted).total_seconds())>120:continue
        result.append(dict(message_id=source['id'],deadline=e.get('deadline'),activity_state=e.get('activity_state',''),published_at=e['published_at'],kind='checkin_activity',evidence=e.get('field_evidence',{}).get('deadline') or e.get('field_evidence',{}).get('activity_state') or '学习通签到活动结束时间：'+str(e.get('deadline')),activity_id=e['activity_id'],course_id=e['course_id'],class_id=e['class_id']))
    return result


def references(db,message):
    return [r for r in observations(db,message) if r.get('deadline')]


def unique(refs):
    return bool(refs) and len({tuple(r[k] for k in ('activity_id','course_id','class_id','deadline')) for r in refs})==1


def verification(db,message):
    from .time_evidence import key
    from .core import now_iso
    refs=observations(db,message)
    if not refs:return 'unverified'
    identities={tuple(r[k] for k in ('activity_id','course_id','class_id')) for r in refs}
    if len(identities)!=1:return 'ambiguous'
    if any(r.get('activity_state')=='ended' for r in refs):return 'ended'
    if not unique(refs):return 'ambiguous'
    return 'ended' if key(refs[0]['deadline'])<=key(now_iso()) else 'verified'


def task_verification(db,task):
    from .task_identity import normalized
    states=[]
    for row in db.execute('SELECT m.data FROM sources s JOIN messages m ON m.id=s.message_id WHERE s.task_id=?',(task['id'],)):
        message=json.loads(row['data'])
        if is_checkin(message,db):
            states.append(verification(db,message))
    if not states:return ''
    for state in ('ended','ambiguous','unverified'):
        if state in states:return state
    return 'verified'
