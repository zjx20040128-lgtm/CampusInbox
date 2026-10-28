"""User-pasted WeChat/QQ messages; no account login or chat-history access."""
import re
from .core import clean_string,parse_timestamp,parse_message,ValidationError

PLATFORMS={'wechat':'微信','qq':'QQ'}


def candidates(text,published_at,course,scope):
    parsed=parse_message(text,published_at or '2000-01-01T00:00:00+08:00',course,scope)
    if not published_at:
        for candidate in parsed:
            if not re.search(r'\d{4}\s*[年/-]\s*\d{1,2}',candidate.get('deadline_evidence','')):
                candidate.update(deadline=None,date_precision='unknown',deadline_evidence='')
                candidate['warnings']=[w for w in candidate.get('warnings',[]) if not w.startswith(('截止日期早于','原文未写年份'))]+['发布时间未知，不推算相对日期或年份。']
    return parsed


def ingest(inbox,body,analyzer=None):
    if not isinstance(body,dict) or set(body)-{'platform','text','conversation','sender','published_at','course','mode'}:raise ValidationError('聊天导入字段不支持。')
    platform=body.get('platform')
    if not isinstance(platform,str) or platform not in PLATFORMS:raise ValidationError('请选择微信或QQ来源。')
    text=clean_string(body.get('text',''),'消息正文',30000,True)
    group=clean_string(body.get('conversation',''),'群名或会话',100,True)
    sender=clean_string(body.get('sender',''),'发件人',100)
    course=clean_string(body.get('course',''),'课程',100)
    published=body.get('published_at')
    if published is not None and published!='':published=parse_timestamp(published).replace(microsecond=0).isoformat()
    else:published=None
    mode=body.get('mode','rules')
    if mode not in ('rules','agent'):raise ValidationError('提取模式无效。')
    # Unknown publication must never reach a model with an import-clock anchor.
    analysis=analyzer.analyze(text,published,course,group) if published and analyzer is not None else None
    result=inbox.ingest(text,source=PLATFORMS[platform]+' · 文本导入',captured_at=published,course=course,scope=group,
        candidates=analysis['candidates'] if analysis else candidates(text,published,course,group),
        mode=analysis['mode'] if analysis else 'rules',trace=analysis['trace'] if analysis else [],
        _chat_import=dict(platform=platform,conversation=group,sender=sender,published_at=published))
    return result
