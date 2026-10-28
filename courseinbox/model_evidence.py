"""Conservative checks for model additions and evidence-checked draft corrections."""
import re
from .core import parse_message,extract_deadline,parse_timestamp,preparation_details,TASK_PATTERN,REQUEST_NEGATION
from .task_identity import canonical_title,normalized


def grounded_title(candidate,source):
    title=canonical_title(candidate['title'],candidate.get('course',''))
    if any(normalized(canonical_title(c.get('title',''),c.get('course','')))==normalized(title) for c in source.get('rule_candidates',[])):
        return candidate['title']
    head=re.match(r'^('+TASK_PATTERN+r')(?:\s*[:：]|\s*(?=提交|完成|上传|上交|交|准备|携带))',title)
    if not head:return candidate['title']
    parsed=parse_message(source['text'],source['captured_at'],candidate.get('course',''),source.get('scope',''))
    matches=[c for c in parsed if normalized(c['title'])==normalized(head[1])]
    return matches[0]['title'] if len(matches)==1 else candidate['title']


def task_context(candidate,source):
    """Use a unique named task block instead of a whole multi-task model quote."""
    title=normalized(canonical_title(candidate['title'],candidate.get('course','')))
    parsed=parse_message(source['text'],source['captured_at'],candidate.get('course',''),source.get('scope',''))
    matches=[c for c in parsed if normalized(canonical_title(c['title'],c.get('course','')))==title]
    if len(matches)==1 and len(parsed)==1:return source['text']
    return matches[0]['evidence'] if len(matches)==1 else candidate['evidence']


def has_task_instruction(candidate,source,context):
    title=normalized(canonical_title(candidate['title'],candidate.get('course','')))
    if any(normalized(canonical_title(c.get('title',''),c.get('course','')))==title for c in source.get('rule_candidates',[])):
        return True
    action=r'提交|上交|上传|完成|阅读|预习|准备|携带|带|参加|研讨|讨论|观看|汇报|绘图|查阅|整理|复习|练习|设计|实现|撰写|交(?=作业|报告|论文|材料|源码|源代码|到|至|给)'
    request=r'(?:请|必须|务必|需要|要求|应当|须|需|记得)[^。！？；;\n]{0,24}(?:'+action+r')'
    imperative=r'(?:^|[。！？；;，,\n])\s*(?:'+action+r')'
    metadata=r'(?:作业|任务|实验)名称\s*[:：]|(?:'+TASK_PATTERN+r')\s*[:：]?\s*(?:截止|最晚|开始|结束|考试时间|提交时间)'
    scheduled=r'(?:考试|测验|汇报|答辩)[^。！？；;\n]{0,24}(?:举行|进行|开始)|(?:举行|进行)[^。！？；;\n]{0,12}(?:考试|测验|汇报|答辩)'
    clauses=[c for c in re.split(r'[。！？；;，,\n]',context) if not re.search(REQUEST_NEGATION+r'(?:再)?(?:'+action+r')',c)]
    return any(re.search(request+'|'+imperative+'|'+metadata+'|'+scheduled,c) for c in clauses)


def supported_submission(method,evidence,context):
    if not evidence or evidence not in context:return False
    channels=(r'学习通',r'邮箱|邮件',r'纸质|纸面|打印|手写',r'课堂|现场',r'微信',r'QQ')
    return all(not re.search(channel,method,re.I) or re.search(channel,evidence,re.I) for channel in channels)


def supported_deadline(candidate,source,context):
    """A quoted date must belong to this task and mean deadline/completion time."""
    from .intake_policy import _deadline_segment
    evidence=candidate.get('deadline_evidence','')
    if not evidence or evidence not in context:return False
    segment=_deadline_segment(context)
    if not segment:
        preparation=preparation_details(context)
        segment=preparation.get('deadline_text','') if preparation else ''
    if not segment:return False
    value,_,_,_=extract_deadline(segment,parse_timestamp(source['captured_at']))
    return value==candidate['deadline']


def deadline_correction(rule,model,text,published_at):
    """Correct only an explicitly misclassified publication/start date in a draft.

    Structured platform evidence is authoritative until a human resolves a
    disagreement. Absence of evidence is not proof that a rule value is wrong.
    """
    if not misclassified_date(rule,text,published_at):return False
    context=dict(text=text,captured_at=published_at,scope=model.get('scope',''))
    return supported_deadline(model,context,task_context(model,context))


def misclassified_date(rule,text,published_at):
    if not published_at or rule.get('field_evidence',{}).get('deadline'):return False
    evidence=rule.get('deadline_evidence','')
    if not evidence or evidence not in text:return False
    if extract_deadline(evidence,parse_timestamp(published_at))[0]!=rule.get('deadline'):return False
    # Match the actual quoted occurrence and its label; a bare date alone is
    # insufficient to discard a rule value. Reject repeated ambiguous quotes.
    if text.count(evidence)!=1:return False
    prefix=text[:text.index(evidence)].split('\n')[-1][-30:]
    return bool(re.search(r'(?:发布时间|发布于|通知时间|开始时间|开始于)\s*[:：]?\s*$',prefix))


def unannounced_deadline_evidence(rule,model,text,published_at):
    if not misclassified_date(rule,text,published_at):return ''
    context=task_context(model,dict(text=text,captured_at=published_at,scope=model.get('scope','')))
    pending=re.search(r'(?:截止(?:时间|日期)?|提交(?:时间|日期))\s*[:：]?\s*(?:尚未公布|未公布|另行通知|待定|暂未确定)',context)
    if not pending:return ''
    # Contradictory explicit dates still need a human; do not erase them.
    remaining=context.replace(rule.get('deadline_evidence',''),'')
    if re.search(r'\d{1,2}\s*(?:月|[-/])\s*\d{1,2}|今天|明天|后天|(?:本|下)?周[一二三四五六日天]',remaining):return ''
    if re.search(r'(?:截止(?:时间|日期)?|结束时间|最晚)\s*[:：]?\s*(?:\d|今天|明天|后天|下周|本周)',context):return ''
    return pending[0]
