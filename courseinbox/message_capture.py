"""Stable task-center content versions, excluding live countdown observations."""
import hashlib
import json
import re
from .task_identity import platform_identity


def without_countdown(value):
    value=re.sub(r'(^|[；;，,\n])[ \t]*(?:剩余|还剩)\s*[:：]?\s*(?:\d+(?:\.\d+)?\s*(?:天|小时|分钟|时|分|秒)\s*)+(?=$|[；;，,\n])',r'\1',value or '')
    return re.sub(r'[；;]\s*[；;]+','；',value).strip(' \t\r\n；;，,')


def capture_key(external,course,scope,text):
    if not external or external.get('kind')!='task_center':return None
    identity=platform_identity(external.get('url',''))
    if not identity:return None
    fields={name:external.get(name,default) for name,default in (
        ('title',''),('deadline',None),('description',''),('submission_method',''),
        ('teacher',''),('task_type','assignment'),('attachments',[]),('platform_status',''))}
    # Keep explicit instructions and absolute date evidence. Only the live timer
    # may disappear; it cannot define either a deadline or a new content version.
    fields['text']=without_countdown(text)
    fields['time_evidence']=without_countdown(external.get('field_evidence',{}).get('deadline',''))
    payload=json.dumps([identity,course,scope,fields],ensure_ascii=False,sort_keys=True)
    return 'task-capture:'+hashlib.sha256(payload.encode()).hexdigest()
