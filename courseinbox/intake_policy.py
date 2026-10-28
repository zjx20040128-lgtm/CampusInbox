"""Evidence-based eligibility for new work collected automatically from Chaoxing."""
import re


_DATE = r'(?:(?:\d{4})\s*[年/-]\s*)?\d{1,2}\s*[月/-]\s*\d{1,2}(?:\s*[日号])?|今天|今日|明天|明日|后天|后日|(?:(?:本|下)周|星期|周)[一二三四五六日天]'
_DEADLINE_CUE = r'截止(?:时间|日期)?|截至|最晚|提交时间|结束(?:时间|日期)'
_TASK = r'(?:任务|作业|实验(?:报告)?|报告|考试|测验)'
_SUBMITTED = r'(?:已提交|已经提交|提交成功|已交|已批阅|已批改)'
_ENDED = r'(?:已结束|已经结束|已截止|已过期|已关闭|已收卷|已完成)'


def is_automatic_message(message):
    external = message.get('external') or {}
    return external.get('platform') == 'chaoxing-web' and external.get('kind', 'chat') in ('chat', 'course_notice', 'task_center', 'checkin_activity')


def is_reminder_notice(candidate, message):
    """Recognize a platform countdown/status template, never a generic reminder word.

    A reminder saying work will end soon does not mean the work has ended. New
    requirements or explicit deadline changes must still follow normal review.
    Inspect the candidate block so one reminder cannot hide another task.
    """
    if not is_automatic_message(message) or message.get('external',{}).get('kind')=='task_center':return False
    text=candidate.get('evidence') or message.get('text','')
    lines=[line.strip().strip('\u200b\ufeff') for line in text.splitlines() if line.strip().strip('\u200b\ufeff')]
    if not lines or not re.fullmatch(r'(?:作业|任务|考试|测验)(?:即将)?(?:结束|截止|到期)提醒[：:！!。]?',lines[0]):return False
    if not re.search(r'课程名称\s*[：:]\s*\S+',text) or not re.search(r'(?:作业|任务|考试|测验)名称\s*[：:]\s*\S+',text):return False
    from .core import DEADLINE_CHANGE_PATTERN
    if re.search(DEADLINE_CHANGE_PATTERN,text) or re.search(r'取消|撤销|作废',text):return False
    status_seen=False
    duration=r'(?:[\d一二三四五六七八九十百半两]+\s*(?:个)?(?:小时|分钟|天|日|周)\s*)+'
    for line in lines[1:]:
        if re.fullmatch(r'(?:课程|作业|任务|考试|测验)名称\s*[：:]\s*\S.*',line):continue
        for clause in re.split(r'[。；;，,！!]',line):
            clause=clause.strip()
            if not clause:continue
            countdown=re.fullmatch(r'(?:你的|您的|该|本次)?'+_TASK+r'(?:还有|还剩|剩余)\s*'+duration+r'(?:就要|即将|将)?(?:结束|截止|到期)',clause)
            if countdown or _closed_status_statement(clause,_ENDED):status_seen=True
            elif not re.fullmatch(r'请(?:尽快|及时)(?:作答|完成|提交|查看)|请查看结果',clause):
                # Additional prose can contain new requirements or another task.
                return False
    return status_seen


def _deadline_segment(text):
    from .core import DEADLINE_CHANGE_PATTERN
    change = re.search(DEADLINE_CHANGE_PATTERN, text)
    if change:
        return text[change.start():]
    cue = re.search(_DEADLINE_CUE, text)
    if cue:
        tail=text[cue.end():]
        tail=re.sub(r'^[ \t:：]*(?:\r?\n[ \t]*){1,2}(?='+_DATE+r')','：',tail,count=1)
        after = re.split(r'[。；;，,\n]', tail, maxsplit=1)[0]
        if re.search(_DATE, after):
            # Starting at the cue prevents a publication/name date from winning.
            return text[cue.start():cue.end()] + after
        before = re.split(r'[。；;，,\n]', text[:cue.start()])[-1]
        dates = list(re.finditer(_DATE, before))
        return before[dates[-1].start():] if dates else ''
    for clause in re.split(r'[。；;，,\n]', text):
        date = re.search(_DATE, clause)
        if not date:
            continue
        tail = clause[date.end():]
        by = re.match(r'[^。；;，,\n]{0,24}?(?:之前|以前|前)(?:提交|上传|上交|完成|阅读|预习)', tail)
        on = re.search(r'(?:请|务必|须|需)?(?:于|在)\s*$', clause[:date.start()]) and re.match(r'[^。；;，,\n]{0,16}?(?:提交|上传|上交|完成|阅读|预习)', tail)
        if by or on:
            return clause[date.start():]
    return ''


def automatic_candidate(candidate, message):
    """Copy an automatic text candidate, accepting only deadlines with source context.

    Structured task-center deadlines are separate platform fields. Other sources
    need a deadline cue or a dated instruction; task names/publication dates alone
    cannot make work historical. Raw messages and input candidates stay intact.
    """
    result = dict(candidate)
    if not (is_automatic_message(message) or message.get('chat_import')) or message.get('external',{}).get('kind') in ('task_center','checkin_activity'):
        return result
    from .core import extract_deadline, parse_timestamp
    from .time_evidence import publication
    published=publication(message)
    anchor=parse_timestamp(published+'T00:00:00+08:00' if published and len(published)==10 else published or '2000-01-01T00:00:00+08:00')
    text = candidate.get('evidence') or message.get('text', '')
    segment = _deadline_segment(text)
    if segment:
        # The general parser's word boundary would misread "2026-09-15前".
        segment = re.sub(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})(?=[^\d\s])', r'\1 ', segment)
        deadline, precision, evidence, warnings = extract_deadline(segment, anchor)
        if not published:
            warnings=[w for w in warnings if not w.startswith('截止日期早于消息发布时间')]
            if deadline and not re.search(r'\d{4}\s*[-/年]\s*\d{1,2}',evidence):
                deadline,precision=None,'unknown'
                warnings=['发布时间未知，无法推算相对日期或年份，请核对截止时间。']
        # The inserted separator is analysis-only; deadline evidence stays verbatim.
        evidence = evidence.strip()
        if evidence and evidence not in text:
            evidence = re.sub(r'(?<=\d) (?=前)', '', evidence)
    else:
        deadline, precision, evidence = None, 'unknown', ''
        if not candidate.get('deadline'):
            return result
        warnings = ['原文日期未明确作为截止日期，保留待核对。']
    result.update(deadline=deadline, date_precision=precision, deadline_evidence=evidence)
    old_warnings = candidate.get('warnings', [])
    deadline_warnings = ('原文日期不存在', '原文时间不存在', '原文未写年份', '原文未写具体时刻', '截止日期早于消息发布时间', '未识别到明确截止日期', '原文日期未明确作为截止日期')
    result['warnings'] = list(dict.fromkeys([warning for warning in old_warnings if not warning.startswith(deadline_warnings)] + warnings))
    return result


def _closed_status_statement(clause, status):
    match = re.search(_TASK + r'\s*(?:状态\s*)?[：:]?\s*' + status + r'(?:了)?[！!]?\s*$', clause)
    if not match:
        return False
    # A group/conditional subject describes eligibility, not this task's state.
    return not re.search(r'如果|假如|假设|如若|倘若|若|当|是否|确认|同学|学生|有人|部分人', clause[:match.start()])


def _status_reason(candidate, message):
    external = message.get('external') or {}
    if external.get('kind') == 'task_center':
        status = external.get('platform_status', candidate.get('platform_status', ''))
        if re.search(_SUBMITTED, status) or status.strip() in ('待批阅','待批改'):
            return 'already_submitted'
        if re.search(_ENDED, status):
            return 'task_ended'
    text = candidate.get('evidence') or message.get('text', '')
    for clause in re.split(r'[。；;，,\n]', text):
        clause = clause.strip()
        if re.match(r'^任务结束提醒(?:$|\s|[：:！!])', clause):
            return 'task_ended'
        submitted = re.match(r'^(?:你|您|我)\s*' + _SUBMITTED + r'(?P<object>[^。]{0,12}' + _TASK + r')(?:了)?[！!]?\s*$', clause)
        if _closed_status_statement(clause, _SUBMITTED) or (submitted and not re.search(r'一半|部分', submitted['object'])):
            return 'already_submitted'
        if _closed_status_statement(clause, _ENDED):
            return 'task_ended'
    return ''


def archive_reason(candidate, message, now):
    """Return a stable reason code, or '' when new work should remain reviewable.

    The caller must first exclude a candidate matched to an existing task. This
    policy never archives update/cancel instructions and never infers completion
    from publication age, unknown deadlines, or another student's submission.
    """
    if is_reminder_notice(candidate,message):return 'reminder_only'
    if not is_automatic_message(message) or candidate.get('operation', 'create') != 'create' or candidate.get('deadline_change_requested'):
        return ''
    text = candidate.get('evidence') or message.get('text', '')
    if message['external'].get('kind') != 'task_center' and re.search(_TASK + r'[^。；;，,\n]{0,24}(?:取消|撤销|作废)|(?:取消|撤销|作废)[^。；;，,\n]{0,24}' + _TASK, text):
        # An unclear cancellation still needs review, even if matching failed.
        return ''
    reason = _status_reason(candidate, message)
    if reason:
        return reason
    from .core import CN, deadline_instant, parse_timestamp
    deadline = automatic_candidate(candidate, message).get('deadline')
    if not deadline:
        return ''
    moment = parse_timestamp(now) if isinstance(now, str) else now.astimezone(CN)
    cutoff = deadline_instant(deadline)
    expired = cutoff <= moment if len(deadline) == 10 else cutoff < moment
    return 'deadline_passed' if expired else ''


def should_archive_automatic(candidate, message, now):
    return bool(archive_reason(candidate, message, now))
