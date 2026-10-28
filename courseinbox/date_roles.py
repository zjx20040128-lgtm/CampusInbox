"""Explicit non-deadline date roles and an evidence-guarded, opt-in repair."""
import json
import re

DATE=r'(?:(?:\d{4})\s*[年/.-]\s*)?\d{1,2}\s*[月/.-]\s*\d{1,2}(?:\s*[日号])?(?:[T \t]+\d{1,2}\s*[:：点时]\s*\d{1,2}(?::\d{2})?)?|今天|今日|明天|明日|后天|后日|(?:(?:本|下)周|星期|周)[一二三四五六日天]'
NON_DEADLINE=re.compile(r'(?:发布(?:时间|日期|于)|通知时间|开始(?:时间|日期|于)|起始(?:时间|日期)|创建时间|更新时间|采集时间|接收时间)\s*[:：]?\s*(?P<date>'+DATE+r')')


def mask_non_deadline_dates(text):
    # Preserve positions/newlines and the exact source separately. End dates survive.
    return NON_DEADLINE.sub(lambda m:re.sub(r'[^\r\n]',' ',m[0]),text)


def matches_non_deadline(text,deadline,anchor):
    from .core import extract_deadline
    return any(extract_deadline(m['date'],anchor)[0]==deadline for m in NON_DEADLINE.finditer(text))


def correct_task(inbox,task_id,expected_version):
    """Explicit repair only: positive role evidence, no valid deadline, full audit."""
    from .core import Conflict,parse_timestamp,now_iso,extract_deadline
    from .time_evidence import source_messages,publication
    from .intake_policy import _deadline_segment
    with inbox.lock,inbox.connection() as db:
        db.execute('BEGIN IMMEDIATE');task=inbox._task(db,task_id)
        if type(expected_version) is not int or task['version']!=expected_version:raise Conflict('任务版本已变化，请重新核对。')
        if not task.get('deadline'):return task
        proof=[]
        for message in source_messages(db,task):
            ext=message.get('external',{});published=publication(message,db)
            anchor=parse_timestamp(published+'T00:00:00+08:00' if published and len(published)==10 else published or '2000-01-01T00:00:00+08:00')
            text=message.get('text','');segment=_deadline_segment(text)
            if ext.get('kind')=='task_center' and ext.get('deadline') or segment and extract_deadline(segment,anchor)[0]:
                raise Conflict('来源中存在明确截止时间，请核对后处理，不能直接清空。')
            if matches_non_deadline(text,task['deadline'],anchor):proof.append(message['id'])
        if not proof:raise Conflict('没有证据证明当前日期被误认，不能自动清空。')
        before=dict(task)
        task.update(deadline=None,date_precision='unknown',version=task['version']+1,updated_at=now_iso(),deadline_correction=dict(reason='non_deadline_date',previous_deadline=before['deadline'],source_message_ids=proof))
        task.pop('deadline_basis',None);task.pop('deadline_reviewed_keys',None)
        inbox._save_task(db,task);inbox._history(db,task,before,'deadline_misclassification_corrected',proof[0])
        return task
