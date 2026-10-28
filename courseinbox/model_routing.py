"""Full-template verification; uncertainty always retains model assistance."""
import re
from .core import normalize,extract_deadline,parse_timestamp,parse_message,TASK_PATTERN


def verified_template(text,candidates,published_at):
    if len(candidates)!=1:return False
    c=candidates[0]
    if c.get('operation')!='create' or c.get('warnings') or c.get('requirements') or not c.get('matchable'):return False
    fields={}
    labels={'课程名称':'course','作业名称':'title','任务名称':'title','截止时间':'deadline','结束时间':'deadline','提交方式':'submission_method'}
    for line in text.strip().splitlines():
        match=re.fullmatch(r'\s*([^:：]+)\s*[:：]\s*(\S[^\r\n]*?)\s*',line)
        if not match or match[1].strip() not in labels:return False
        key=labels[match[1].strip()]
        if key in fields:return False
        fields[key]=match[2]
    if not {'course','title','deadline'}<=fields.keys():return False
    if any(normalize(fields[key])!=normalize(c.get(key,'')) for key in ('course','title','submission_method') if key in fields):return False
    if 'submission_method' not in fields and c.get('submission_method'):return False
    if any(re.search(r'[。；;，,]|如果|若|除外|延期|补交|附件|详见',value) for key,value in fields.items() if key!='deadline'):return False
    if re.search(r'[。；;，,]|以及|并|和|与|除外|取消|延期|调整|改为',fields['title']):return False
    if len(re.findall(TASK_PATTERN,fields['title']))!=1:return False
    if not re.fullmatch(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?(?:\s+\d{1,2}[:：]\d{2})?',fields['deadline']):return False
    due,precision,_,warnings=extract_deadline(fields['deadline'],parse_timestamp(published_at))
    parsed=parse_message(text,published_at,c.get('course',''),c.get('scope',''))
    if len(parsed)!=1 or parsed[0]['kind']!=c.get('kind'):return False
    return bool(due and due==c.get('deadline') and precision==c.get('date_precision') and not warnings)
