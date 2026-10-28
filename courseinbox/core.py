"""CourseInbox domain: provenance, draft review and versioned tasks. Stdlib only."""
from __future__ import annotations
import contextlib
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

CN = timezone(timedelta(hours=8))
STATUSES = {'pending', 'in_progress', 'done', 'submitted', 'cancelled'}
KINDS = {'assignment', 'exam', 'experiment', 'project', 'presentation', 'other'}
CONFIDENCE = {'low','medium','high'}
DEADLINE_CHANGE_PATTERN = r'(?:延期(?:到|至|为|成)|延至|推迟(?:到|至|为|成)|改(?:为|到|至|成)|调整(?:为|到|至|成)|变更(?:为|到|至|成)|修改(?:为|到|至|成)|更改(?:为|到|至|成)|更新(?:为|到|至|成)|截止(?:时间|日期)?\s*(?:(?:已|现|将)\s*)?(?:调整|变更|修改|更改|更新|改)(?:为|到|至|成)|(?:调整|变更|修改|更改|更新|改)\s*截止(?:时间|日期)?\s*(?:(?:已|现|将)\s*)?(?:为|到|至|成))'

class ValidationError(ValueError):
    pass
class Conflict(ValidationError):
    pass
class NotFound(ValidationError):
    pass

def now_iso():
    return datetime.now(CN).replace(microsecond=0).isoformat()

def parse_timestamp(value):
    if not isinstance(value, str):
        raise ValidationError('消息时间必须是带时区的 ISO 时间。')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValidationError('消息时间无效，请使用带时区的 ISO 时间。') from None
    if result.tzinfo is None:
        raise ValidationError('消息时间缺少时区。')
    return result.astimezone(CN)

def clean_string(value, name, maximum=160, required=False):
    if not isinstance(value, str):
        raise ValidationError(f'{name}必须为文本。')
    value = value.strip()
    if len(value) > maximum:
        raise ValidationError(f'{name}最多 {maximum} 个字符。')
    if required and not value:
        raise ValidationError(f'请填写{name}。')
    return value

def normalize(value):
    return re.sub(r'[\W_]+', '', value, flags=re.UNICODE).lower()

def validate_deadline(value):
    if value is None or value == '':
        return None, 'unknown'
    if not isinstance(value, str):
        raise ValidationError('截止日期必须为文本。')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value).isoformat(), 'date'
        result = parse_timestamp(value)
        return result.replace(microsecond=0).isoformat(), 'minute'
    except (ValueError, ValidationError):
        raise ValidationError('截止日期无效，使用 YYYY-MM-DD 或带时区时间。') from None

def deadline_instant(value):
    if not value:
        return None
    if len(value) == 10:
        # Only the calendar day is known: overdue starts next day, never guess 23:59.
        return datetime.combine(date.fromisoformat(value) + timedelta(days=1), datetime.min.time(), CN)
    return parse_timestamp(value)

def extract_deadline(text, anchor):
    from .date_roles import mask_non_deadline_dates
    text=mask_non_deadline_dates(text)
    warnings = []
    change = re.search(DEADLINE_CHANGE_PATTERN + r'\s*[:：]?', text)
    segment = text[change.end():] if change else text
    if not change:
        timed_task_end = re.search(r'结束(?:时间|日期)\s*[:：]?', text) if re.search(r'开始(?:时间|日期)',text) and re.search(r'作业|考试|测验',text) else None
        cue = timed_task_end or re.search(r'(?:截止(?:时间|日期)?(?:为|到|至)?|截至|最晚|提交时间)\s*[:：]?', text)
        if cue:
            prefix=re.split(r'[。；;，,\n]',text[:cue.start()])[-1]
            has_prefix_date=re.search(r'\d{1,2}\s*[月/-]\s*\d{1,2}|今天|今日|明天|明日|后天|后日|(?:周|星期)[一二三四五六日天]',prefix)
            segment=prefix if has_prefix_date else text[cue.end():]
    explicit = re.search(r'(?:(\d{4})\s*[年/-]\s*)?(\d{1,2})\s*[月/-]\s*(\d{1,2})(?:\s*[日号]|\b)', segment)
    chosen = None
    evidence = ''
    end = 0
    if explicit:
        year = int(explicit.group(1) or anchor.year)
        try:
            chosen = date(year, int(explicit.group(2)), int(explicit.group(3)))
        except ValueError:
            return None, 'unknown', explicit.group(0), ['原文日期不存在，请手动核对。']
        end = explicit.end()
        evidence = explicit.group(0)
        if not explicit.group(1):
            warnings.append('原文未写年份，暂按消息发布年份，请核对。')
    else:
        rel = re.search(r'今天|今日|明天|明日|后天|后日|(?:(?:本|下)周|星期|周)[一二三四五六日天]', segment)
        if rel:
            token = rel.group(0)
            if token in ('今天', '今日', '明天', '明日', '后天', '后日'):
                offset = {'今天': 0, '今日': 0, '明天': 1, '明日': 1, '后天': 2, '后日': 2}[token]
                chosen = anchor.date() + timedelta(days=offset)
            else:
                weekday = '一二三四五六日'.index(token[-1].replace('天', '日'))
                monday = anchor.date() - timedelta(days=anchor.weekday())
                if token.startswith('下周'):
                    chosen = monday + timedelta(days=7 + weekday)
                elif token.startswith('本周'):
                    chosen = monday + timedelta(days=weekday)
                else:
                    chosen = anchor.date() + timedelta(days=(weekday - anchor.weekday()) % 7)
                    warnings.append('原文未说明哪一周，请核对日期。')
            end, evidence = rel.end(), token
    if chosen is None:
        return None, 'unknown', '', ['未识别到明确截止日期，请核对或留空。']
    # A time must follow the selected date within the same short clause.
    tail = re.split(r'[。；;\n]', segment[end:], maxsplit=1)[0][:36]
    tm = re.search(r'(?:(上午|下午|晚上|中午)\s*)?(\d{1,2})\s*[:：点时]\s*(\d{1,2})?(?:分)?', tail)
    if tm:
        h, m = int(tm.group(2)), int(tm.group(3) or 0)
        period = tm.group(1)
        if period in ('下午', '晚上') and h < 12:
            h += 12
        if period == '上午' and h == 12:
            h = 0
        try:
            dt = datetime(chosen.year, chosen.month, chosen.day, h, m, tzinfo=CN)
        except ValueError:
            return None, 'unknown', evidence + tm.group(0), ['原文时间不存在，请手动核对。']
        value, precision = dt.isoformat(), 'minute'
        evidence += tail[:tm.end()]
    else:
        value, precision = chosen.isoformat(), 'date'
        warnings.append('原文未写具体时刻，保留为日期。')
    if chosen < anchor.date():
        warnings.append('截止日期早于消息发布时间，请核对年份和历史消息。')
    return value, precision, evidence, warnings

TASK_PATTERN = r'第[零〇一二三四五六七八九十百\d]+次(?:作业|实验|测验|考试)|(?:实验|作业|报告)\s*[零〇一二三四五六七八九十\d]+|(?:期中|期末)考试'

REQUEST_NEGATION = r'(?:无需|不用|不必|不需|不要|不需要|不要求|请勿|勿|暂(?:时)?不|不得|不能)'

def detect_operation(text, title):
    base='update' if re.search(r'延期|延至|推迟|改(?:为|到|至|成)|调整|变更(?:为|到|至|成)|修改(?:为|到|至|成)|更改(?:为|到|至|成)|更新(?:为|到|至|成)',text) else 'create'
    if not re.search(r'取消|撤销|作废|无需提交|不用提交|不必提交|免交',text):
        return base, []
    negative=re.search(r'(?:不(?:要|会|再)?|未(?:被)?)(?:取消|撤销|作废)',text)
    narrowed=re.search(r'(?:取消|撤销|作废|无需提交|不用提交)[^。；;，,\n]{0,18}(?:纸质|纸面|电子|打印|手写|线下|版本|版)',text)
    continuing=re.search(r'仍需|仍须|还需|照常|继续提交|继续完成',text)
    if negative or narrowed or continuing:
        return base, ['取消用语包含否定、材料限定或继续提交要求，保留任务；请核对原文。']
    escaped=re.escape(title)
    explicit=re.search(r'(?:取消|撤销|作废)\s*(?:本次|该|这次)?\s*'+escaped,text) or re.search(escaped+r'\s*(?:已|现已|将)?\s*(?:取消|撤销|作废|无需提交|不用提交|不必提交|免交)',text)
    standalone=any(re.fullmatch(r'\s*(?:现已|已|现|本次(?:任务|作业)?|该(?:任务|作业)?)?\s*(?:取消|撤销|作废|无需提交|不用提交|不必提交|免交)\s*[！!]?\s*',clause) for clause in re.split(r'[。；;，,\n]',text))
    if explicit or standalone:
        return 'cancel', []
    return base, ['取消对象不明确，保留任务；请核对是否只是材料要求变化。']

def preparation_details(text):
    # Repair soft Chinese OCR wraps for analysis only; stored evidence stays untouched.
    compact=re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])','',text)
    clauses=re.split(r'[。；;！!？?]',compact)
    negative=r'(?:'+REQUEST_NEGATION+r'|已完成|已经完成)[^，,]{0,12}$'
    requirements=[]
    verbs=[]
    for clause in clauses:
        quoted=[(match.start(),match.end()) for match in re.finditer(r'《[^》]+》',clause)]
        for action in re.finditer(r'阅读|预习|研读|预读',clause):
            if any(start<=action.start()<end for start,end in quoted):
                continue
            prefix=clause[max(0,action.start()-40):action.start()]
            body=clause[action.end():]
            if re.search(negative,prefix) or re.match(r'[了过]',body):
                continue
            # A listed attachment name is evidence, not another reading instruction.
            if re.match(r'说明\s*[.·．]\s*doc',body,re.I) and prefix.endswith('课前'):
                continue
            if not re.search(r'请|希望|要求|需要|务必|提前',prefix):
                continue
            object_end=len(body)
            object_quotes=[(match.start(),match.end()) for match in re.finditer(r'《[^》]+》',body)]
            for boundary in re.finditer(r'[，,\n]|(?:并|然后)(?:请|在|于)?',body):
                if not any(start<=boundary.start()<end for start,end in object_quotes):
                    object_end=boundary.start()
                    break
            object_text=body[:object_end].strip(' ：:')
            if not object_text or re.fullmatch(r'(?:通知中列出的|这[些几]|相关|指定|[零〇一二三四五六七八九十百\d]+份)?(?:材料|资料|文献)',object_text):
                object_text='通知中列出的材料'
            verbs.append(action.group(0))
            requirements.append(action.group(0)+object_text[:100])
    lesson=re.search(r'第[零〇一二三四五六七八九十百\d]+(?:次|节)课',compact)
    lesson=lesson.group(0) if lesson else ''
    topic=re.search(r'(?:主题)?(?:研讨|讨论)',compact)
    preparing=False
    for clause in clauses:
        for action in re.finditer(r'做(?:一下|好)?(?:研讨|讨论)?准备|为[^，,]{0,40}(?:研讨|讨论)[^，,]{0,15}准备|准备(?:一下)?(?:研讨|讨论)',clause):
            prefix=clause[max(0,action.start()-40):action.start()]
            if not re.search(negative,prefix) and (re.search(r'请|希望|要求|需要|务必|提前',prefix) or verbs):
                preparing=True
    if topic and preparing:
        requirements.append('为'+(lesson+'的' if lesson else '')+topic.group(0)+'做好准备')
    action_title=''
    for pattern,label in (
        (r'(?:请|需要|务必|要求)[^。；;，,\n]{0,20}填写[^。；;，,\n]{0,20}问卷','填写问卷'),
        (r'(?:请|需要|务必|要求)[^。；;，,\n]{0,20}带(?:上|着)?[^。；;，,\n]{1,50}(?:电脑|纸|笔)','上课准备'),
        (r'(?:请|需要|务必|要求)[^。；;，,\n]{0,20}(?:扫码|加入|进入)[^。；;，,\n]{0,25}(?:群|微信群)','加入课程群')):
        found=re.search(pattern,compact)
        if found and not re.search(REQUEST_NEGATION,compact[max(0,found.start()-8):found.start()]):
            requirements.append(found.group(0)[:100])
            if not action_title:action_title=label
    if not requirements:
        return None
    warnings=[]
    if re.search(r'(?:具体|详细)?要求(?:请)?(?:见|查看|参见)附件|请(?:查看|参阅)附件',compact):
        attachment=re.search(r'([\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9（）() _-]{1,60})\s*[.·．]\s*(?:docx?|pdf)\b',text,re.I)
        name='“'+attachment.group(1).strip()+'”' if attachment else ''
        requirements.append('查看'+name+'附件，确认具体要求')
        warnings.append('附件正文尚未导入，无法提取其中的具体细则，请打开附件核对。')
    date_marker=r'(?:今天|今日|明天|明日|后天|后日|(?:(?:本|下)周|星期|周)[一二三四五六日天]|(?:\d{4}年)?\d{1,2}月\d{1,2}日?|(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2})'
    before_class=re.search(date_marker+r'[^。；;，,\n]{0,24}(?:上课前|课前|前(?:完成|阅读|预习|研读))',compact)
    deadline_text=before_class.group(0) if before_class else ''
    if not deadline_text:
        deadline_cue=re.search(r'[^。；;，,！!？?\n]{0,50}(?:截止|截至|最晚)[^。；;！!？?\n]{0,60}',compact)
        deadline_text=deadline_cue.group(0) if deadline_cue else ''
    if not deadline_text and action_title=='上课准备':
        class_day=re.search(r'今天上课|明天上课|后天上课',compact)
        deadline_text=class_day.group(0) if class_day else ''
    class_context=bool(re.search(r'课前|上课前',compact))
    if class_context:
        warnings.append('原文要求上课前完成；具体上课时间未给出，请核对课表。')
    if re.search(r'[·]\s*doc|doc\s*[×]|[A-Za-z-]\n[A-Za-z-]',text):
        warnings.append('截图文字可能有识别误差，请核对材料数量和附件名称。')
    title=action_title or lesson+('课前' if class_context else '')+(verbs[0] if verbs else '研讨准备')+('与研讨准备' if verbs and topic and preparing else '')
    return dict(title=title,requirements=list(dict.fromkeys(requirements)),deadline_text=deadline_text,warnings=warnings)

def parse_message(text, captured_at, course='', scope=''):
    text = clean_string(text, '消息', 30000, True)
    anchor = parse_timestamp(captured_at)
    from .relative_deadlines import request as extension_request,duration_hint
    relative=extension_request(text)
    if not relative and not duration_hint(text) and not re.search(r'作业|实验|报告|汇报|展示|演讲|考试|测验|论文|课程设计|提交|上传|截止|签到|答辩', text) and not preparation_details(text):
        return []
    selected_course = course.strip()
    course_label = re.search(r'(?:^|\n)\s*课程(?:名称|名)?\s*[:：]\s*([^\n，,。；;]{1,80})', text)
    course_match = re.search(r'《([^》]{1,80})》|【([^】]{1,80})】', text)
    course_heading = re.match(r'\s*([^\n：:，,。；;《》【】]{1,80})\s*[:：]\s*(.+)', text, re.S)
    heading_course = ''
    if course_heading:
        heading, body = course_heading.group(1).strip(), course_heading.group(2)
        # A leading course heading needs a task on its right. Instruction labels
        # and task headings must not become courses (e.g. "实验一：请提交报告").
        metadata = re.search(r'通知$|提醒$|^(?:(?:任务|作业|实验|考试)(?:名称|标题)?|标题|提交方式|截止(?:时间|日期)?|开始时间|结束时间|发布时间|来源|要求|说明|备注|附件|教师|班级)$', heading)
        instruction = re.match(r'请|注意|截止|提交|上传|完成', heading)
        if (not metadata and not instruction and not re.fullmatch(TASK_PATTERN, heading)
                and re.search(r'[A-Za-z一-鿿]', heading)
                and (re.search(TASK_PATTERN, body) or preparation_details(body))):
            heading_course = heading
    course = selected_course or (course_label.group(1).strip() if course_label else '') or heading_course or (next((x for x in course_match.groups() if x), '') if course_match else '')
    # Separate paragraphs are separate candidates only when each contains a task marker.
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    blocks = paragraphs if len(paragraphs) > 1 and all(re.search(TASK_PATTERN, p) for p in paragraphs) else [text]
    # Split only a new task heading with its own instruction, never a mid-clause
    # reference such as "格式参考实验四". Continuation sentences stay with their task.
    boundary = (r'(?<=[。；;\n])\s*(?=(?:《[^》]{1,80}》\s*)?(?:' + TASK_PATTERN +
                r')\s*(?:[:：，,]|截止|截至|请|需|应|(?:现已?|已)?(?:延期|延至|推迟|取消|撤销|作废)|于|在))')
    separated = []
    for block in blocks:
        start = 0
        for cut in re.finditer(boundary, block):
            previous = block[start:cut.start()]
            following = block[cut.end():]
            before_title, after_title = re.search(TASK_PATTERN, previous), re.search(TASK_PATTERN, following)
            before_course, after_course = re.search(r'《([^》]+)》', previous), re.match(r'《([^》]+)》', following)
            different_course = before_course and after_course and before_course.group(1) != after_course.group(1)
            if before_title and after_title and (before_title.group(0) != after_title.group(0) or different_course):
                separated.append(previous.strip())
                start = cut.start()
        separated.append(block[start:].strip())
    blocks = separated
    shared = re.search(r'(?:^|[。；;\n])\s*((?:以上|上述|这(?:两|几)项)[^。；;\n]{0,12}?(?:均|都|全部|统一)[^。；;\n]+)[。；;\s]*$', text) if len(blocks) > 1 else None
    shared_deadline = shared.group(1) if shared and re.search(r'截止|截至|最晚|延期|延至|推迟', shared.group(1)) else ''
    result = []
    for block in blocks[:20]:
        own_course = re.match(r'《([^》]+)》', block)
        block_course = own_course.group(1) if not selected_course and own_course and len(blocks) > 1 else course
        title_match = re.search(TASK_PATTERN, block)
        named_title = re.search(r'(?:作业|任务)(?:名称|标题)\s*[:：]\s*([^\n，,。；;]{1,100})', block)
        label = re.search(r'(?:任务|标题)\s*[:：]\s*([^\n，,。；;]{1,100})', block)
        generic = re.search(r'实验报告|课程设计|毕业论文|论文|实验|考试|作业|签到|答辩|课程汇报|汇报|展示|演讲|报告', block)
        named_title_value = re.split(r'(?:截止(?:时间|日期)?|截至|最晚|提交时间|延期(?:到|至|为|成)|延至|推迟(?:到|至|为|成))', named_title.group(1), maxsplit=1)[0].strip(' \t：:，,') if named_title else ''
        title = named_title_value or (title_match.group(0) if title_match else (label.group(1) if label else (generic.group(0) if generic else '课程任务')))
        if re.fullmatch(r'(?:作业|实验|任务)\s*(?:\d+|[一二三四五六七八九十百]+)\s*[:：][^\n。；;]{1,120}', block.strip()):
            title = block.strip()
        if re.fullmatch(r'(?:签到码|二维码|位置|手势|拍照|普通|人脸)?签到', block.strip()):
            title = block.strip()
        preparation=preparation_details(block)
        submission = None
        for found in re.finditer(r'(?:提交|上传|上交)\s*[:：]?\s*([^。；;\n]{1,160})', block):
            prefix=block[max(0,found.start()-16):found.start()]
            if not re.search(REQUEST_NEGATION+r'(?:再)?$',prefix):
                submission=found
                break
        preparation_only=bool(preparation and not (title_match or label or submission or re.search(r'考试|测验|签到|答辩',block)))
        operation_text=block + ('\n' + shared_deadline if shared_deadline and shared_deadline not in block else '')
        if preparation_only:
            title=preparation['title']
            operation_text=re.sub(REQUEST_NEGATION+r'(?:再)?(?:提交|上传|上交)','',block)
        operation, operation_warnings = detect_operation(operation_text, title)
        deadline, precision, deadline_evidence, warnings = extract_deadline(shared_deadline or (preparation['deadline_text'] if preparation_only else block), anchor)
        if preparation:
            warnings.extend(preparation['warnings'])
            if preparation_only and precision=='date':
                warnings=[warning for warning in warnings if warning!='原文未写具体时刻，保留为日期。']
        warnings.extend(operation_warnings)
        if not block_course:
            warnings.append('未识别课程，请填写后再确认。')
        if not title_match and not label and not named_title:
            warnings.append('课前任务请核对课次与要求，确认后添加。' if preparation_only else '任务名称较笼统，不自动与其他任务合并。')
        requirements = list(preparation['requirements']) if preparation else []
        if submission:
            body = re.split(r'(?:截止|截至|最晚|于\s*\d|在\s*\d)', submission.group(1))[0]
            for part in re.split(r'[、，,和及+＋]', body):
                part = part.strip(' ：:。 ')
                if part and not re.search(r'\d.*(?:月|日|:)|明天|后天|周[一二三四五六日]|前提交|不用', part):
                    requirements.append(part[:120])
        submission_parts=[];submission_evidence=[]
        stated_submission=re.search(r'(?:提交|上传)方式\s*[:：]\s*([^\n。；;]{1,100})',block)
        if stated_submission:submission_parts.append(stated_submission.group(1).strip());submission_evidence.append(stated_submission.group(0))
        if re.search(r'课堂(?:展示|汇报)',block):submission_parts.append('课堂展示');submission_evidence.append(re.search(r'课堂(?:展示|汇报)',block).group(0))
        platform_upload=re.search(r'([A-Za-z0-9一-鿿]{0,24}?)(?:上传|提交)(?:至|到)?学习通',block)
        if platform_upload:
            item=platform_upload.group(1).strip('请将把于在，,：:。 ')
            submission_parts.append('学习通上传'+item if item else '学习通上传');submission_evidence.append(platform_upload.group(0))
        if re.search(r'(?:发送|提交)(?:至|到)?(?:指定)?邮箱|邮件提交',block):submission_parts.append('邮件提交');submission_evidence.append(re.search(r'(?:发送|提交)(?:至|到)?(?:指定)?邮箱|邮件提交',block).group(0))
        if re.search(r'纸质(?:版|稿|材料)?',block):submission_parts.append('纸质提交');submission_evidence.append(re.search(r'纸质(?:版|稿|材料)?',block).group(0))
        kind = 'other' if preparation_only else 'exam' if re.search(r'考试|测验', title) else ('experiment' if '实验' in title else ('project' if re.search(r'设计|论文', title) else ('presentation' if re.search(r'汇报|展示|演讲|答辩',title) else 'assignment')))
        if '签到' in title:
            kind = 'other'
        deadline_change_requested=bool(re.search(r'(?:延期|延至|推迟)',operation_text) or (re.search(r'(?:截止(?:时间|日期)?|截至|最晚|提交时间)',operation_text) and re.search(r'(?:改|调整|变更|修改|更改|更新)',operation_text)))
        result.append(dict(title=title, course=block_course, scope=scope, deadline=deadline, date_precision=precision, kind=kind,
                           requirements=requirements, operation=operation, matchable=bool(title_match or label or named_title), evidence=text if shared_deadline else block[:1200],
                           deadline_evidence=deadline_evidence, warnings=warnings, captured_at=anchor.isoformat(),submission_method='；'.join(dict.fromkeys(submission_parts)),
                           teacher='',source_url='',platform_status='',confidence='medium',deadline_change_requested=deadline_change_requested,field_evidence={'submission_method':'；'.join(submission_evidence)} if submission_evidence else {}))
    if (relative or duration_hint(text)) and len(result)==1:
        result[0].update(operation='update',deadline_change_requested=True,deadline=None,date_precision='unknown',deadline_evidence='')
    return result

def validate_candidate(candidate, message, edits=None):
    if not isinstance(candidate, dict):
        raise ValidationError('草稿格式无效。')
    c = dict(candidate)
    if edits:
        if not isinstance(edits, dict):
            raise ValidationError('编辑字段必须为对象。')
        allowed = {'title','course','scope','deadline','kind','requirements','submission_method'}
        if set(edits) - allowed:
            raise ValidationError('存在不支持的编辑字段。')
        c.update(edits)
    c['title'] = clean_string(c.get('title', ''), '任务名称', 160, True)
    c['course'] = clean_string(c.get('course', ''), '课程', 100)
    c['scope'] = clean_string(c.get('scope', message['scope']), '班级', 100)
    c['deadline'], c['date_precision'] = validate_deadline(c.get('deadline'))
    if c.get('kind', 'other') not in KINDS:
        raise ValidationError('任务类型无效。')
    c['kind'] = c.get('kind', 'other')
    c['operation'] = c.get('operation', 'create')
    if c['operation'] not in {'create','update','cancel'}:
        raise ValidationError('任务操作无效。')
    requirements = c.get('requirements', [])
    if not isinstance(requirements, list) or len(requirements) > 30:
        raise ValidationError('任务要求必须是最多 30 条的列表。')
    c['requirements'] = list(dict.fromkeys(clean_string(x, '要求内容', 180, True) for x in requirements))
    c['evidence'] = clean_string(c.get('evidence', message['text'][:1200]), '原文依据', 30000)
    if c['evidence'] and c['evidence'] not in message['text']:
        raise ValidationError('草稿依据必须能在消息原文中找到。')
    c['warnings'] = [str(x)[:250] for x in c.get('warnings', [])[:20]]
    c['captured_at'] = message['captured_at']
    c['matchable'] = bool(c.get('matchable', False))
    c['deadline_evidence'] = str(c.get('deadline_evidence', ''))[:300]
    c['deadline_change_requested'] = c.get('deadline_change_requested', False)
    if type(c['deadline_change_requested']) is not bool:
        raise ValidationError('截止变更标记无效。')
    c['submission_method']=clean_string(c.get('submission_method',''),'提交方式',160)
    c['teacher']=clean_string(c.get('teacher',''),'教师',100)
    c['platform_status']=clean_string(c.get('platform_status',''),'平台状态',100)
    source_url=clean_string(c.get('source_url',''),'任务链接',800)
    if source_url:
        parsed=urlsplit(source_url)
        if parsed.scheme!='https' or parsed.netloc not in ('mooc1.chaoxing.com','mooc2-ans.chaoxing.com') or parsed.fragment: raise ValidationError('任务链接必须为学习通官方页面。')
    c['source_url']=source_url
    from .task_identity import identity_parts
    if identity_parts(source_url)['problem']:
        raise ValidationError('学习通链接中的课程、班级或任务编号互相冲突，请核对原文。')
    confidence=c.get('confidence','medium')
    if confidence not in CONFIDENCE: raise ValidationError('识别置信度无效。')
    c['confidence']=confidence
    field_evidence=c.get('field_evidence',{})
    if not isinstance(field_evidence,dict) or len(field_evidence)>12: raise ValidationError('字段依据无效。')
    c['field_evidence']={clean_string(str(k),'字段名',50,True):clean_string(v,'字段依据',240,True) for k,v in field_evidence.items()}
    return c

def task_defaults(task):
    task=dict(task)
    task.setdefault('submission_method','');task.setdefault('teacher','');task.setdefault('source_url','');task.setdefault('platform_status','')
    task.setdefault('confidence','medium');task.setdefault('field_evidence',{})
    return task

def task_key(candidate):
    from .task_identity import name_key,platform_identity
    identity=platform_identity(candidate.get('source_url',''))
    if identity:return 'platform:'+identity
    if not candidate.get('course') or not candidate.get('matchable'):return None
    return name_key(candidate)

def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

class Inbox:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.change_listeners=set()
        with self.connection() as db:
            columns={row['name'] for row in db.execute('PRAGMA table_info(messages)')}
            if columns and not {'sort_at','hidden_at','capture_key'}<=columns:
                backup_directory=self.path.parent/'backups';backup_directory.mkdir(exist_ok=True)
                backup_path=backup_directory/(self.path.stem+'-before-desktop-reliability-'+datetime.now(CN).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.sqlite3')
                destination=sqlite3.connect(backup_path)
                try:db.backup(destination)
                finally:destination.close()
            elif columns and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_identities'").fetchone():
                directory=self.path.parent/'backups';directory.mkdir(exist_ok=True)
                backup=directory/(self.path.stem+'-before-task-identities-'+datetime.now(CN).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.sqlite3')
                destination=sqlite3.connect(backup)
                try:db.backup(destination)
                finally:destination.close()
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, task_key TEXT UNIQUE NOT NULL, data TEXT NOT NULL, version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, message_id TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', task_id TEXT);
            CREATE TABLE IF NOT EXISTS sources(task_id TEXT NOT NULL, message_id TEXT NOT NULL, UNIQUE(task_id,message_id));
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS platform_observations(identity TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cleared_messages(fingerprint TEXT PRIMARY KEY, message_id TEXT NOT NULL, cleared_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_identities(identity TEXT PRIMARY KEY,task_id TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS task_identity_owner ON task_identities(task_id);
            CREATE TABLE IF NOT EXISTS proposal_sources(proposal_id TEXT NOT NULL,message_id TEXT NOT NULL,PRIMARY KEY(proposal_id,message_id));
            CREATE INDEX IF NOT EXISTS proposal_source_message ON proposal_sources(message_id);
            CREATE TABLE IF NOT EXISTS message_supplements(original_message_id TEXT NOT NULL,message_id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS supplement_original ON message_supplements(original_message_id);
            INSERT OR IGNORE INTO proposal_sources SELECT id,message_id FROM proposals;
            ''')
            columns={row['name'] for row in db.execute('PRAGMA table_info(messages)')}
            if 'sort_at' not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN sort_at TEXT NOT NULL DEFAULT ''")
            if 'hidden_at' not in columns:
                db.execute('ALTER TABLE messages ADD COLUMN hidden_at TEXT')
            if 'capture_key' not in columns:
                from .message_capture import capture_key
                if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
                db.execute('ALTER TABLE messages ADD COLUMN capture_key TEXT')
                for row in db.execute('SELECT id,data FROM messages').fetchall():
                    message=json.loads(row['data'])
                    key=capture_key(message.get('external'),message.get('course',''),message.get('scope',''),message.get('text',''))
                    if key:db.execute('UPDATE messages SET capture_key=? WHERE id=?',(key,row['id']))
                # Fold old repeated observations from the feed only. Raw rows,
                # source links, proposal links and task histories remain intact.
                db.execute('''UPDATE messages SET hidden_at=? WHERE hidden_at IS NULL AND capture_key IS NOT NULL
                    AND rowid NOT IN (SELECT MAX(rowid) FROM messages WHERE hidden_at IS NULL AND capture_key IS NOT NULL GROUP BY capture_key)''',(now_iso(),))
            db.execute('CREATE INDEX IF NOT EXISTS messages_capture ON messages(capture_key)')
            for row in db.execute("SELECT id,data FROM messages WHERE sort_at='' ").fetchall():
                message=json.loads(row['data'])
                db.execute('UPDATE messages SET sort_at=? WHERE id=?',(self._message_time(message),row['id']))
            db.execute('CREATE INDEX IF NOT EXISTS messages_feed ON messages(hidden_at,sort_at DESC)')
        self._initialize_identities()
        self.reconcile_automatic_drafts()
    @staticmethod
    def _message_time(message):
        external=message.get('external') or {}
        value=message.get('received_at') if external.get('time_known') is False else message.get('captured_at')
        try:return parse_timestamp(value or message.get('received_at')).astimezone(timezone.utc).isoformat()
        except ValidationError:return '0001-01-01T00:00:00+00:00'
    @contextlib.contextmanager
    def connection(self,notify=True):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
            changed=bool(db.total_changes)
        finally:
            db.close()
        if notify and changed:
            for callback in tuple(self.change_listeners):
                try:callback()
                except Exception:pass
    def subscribe_changes(self,callback):
        self.change_listeners.add(callback)
        return lambda:self.change_listeners.discard(callback)
    def _task(self, db, task_id):
        visited=set()
        while task_id not in visited:
            visited.add(task_id)
            row=db.execute('SELECT data FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not row:raise NotFound('任务不存在。')
            task=task_defaults(json.loads(row['data']))
            if not task.get('merged_into'):return task
            task_id=task['merged_into']
        raise Conflict('任务合并引用异常，请检查本机备份。')
    @staticmethod
    def _task_platform_identities(db, task):
        from .task_identity import platform_identity
        identity=platform_identity(task.get('source_url',''))
        identities={identity} if identity else set()
        identities.update(row['identity'] for row in db.execute('SELECT identity FROM task_identities WHERE task_id=?',(task['id'],)))
        rows=db.execute('SELECT m.data FROM messages m JOIN sources s ON m.id=s.message_id WHERE s.task_id=?',(task['id'],))
        for row in rows:
            external=json.loads(row['data']).get('external',{})
            if external.get('kind')=='task_center':
                identity=platform_identity(external.get('url',''))
                if identity:identities.add(identity)
        return identities
    @classmethod
    def _task_platform_identity(cls,db,task):
        identities=cls._task_platform_identities(db,task)
        return next(iter(identities)) if len(identities)==1 else ''
    def _initialize_identities(self):
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT data FROM tasks').fetchall():
                task=json.loads(row['data'])
                if task.get('merged_into') or task.get('excluded_reason'):continue
                for identity in self._task_platform_identities(db,task):
                    db.execute('INSERT OR IGNORE INTO task_identities VALUES(?,?)',(identity,task['id']))
    def _claim_identities(self,db,task,candidate=None,additional=()):
        from .task_identity import platform_identity
        identities=self._task_platform_identities(db,task)
        identities.update(additional)
        identity=platform_identity((candidate or {}).get('source_url',''))
        if identity:identities.add(identity)
        if len(identities)>1:raise Conflict('来源中出现不同平台任务编号，请先核对，不能将不同任务合并。')
        for identity in identities:
            row=db.execute('SELECT task_id FROM task_identities WHERE identity=?',(identity,)).fetchone()
            if row and self._task(db,row['task_id'])['id']!=task['id']:
                raise Conflict('这个学习通任务已经存在，请刷新后关联来源，不能再创建副本。')
            db.execute('INSERT OR REPLACE INTO task_identities VALUES(?,?)',(identity,task['id']))
    @staticmethod
    def _compatible_identities(candidate,identities):
        from .task_identity import identity_parts
        parts=identity_parts(candidate.get('source_url',''))
        return not identities or any(all(not parts.get(key) or parts[key]==value for key,value in zip(('course','group','kind','number'),identity.split('|'))) for identity in identities)
    def _matching_tasks(self, db, candidate):
        if not task_key(candidate):return []
        from .task_identity import name_key,platform_identity
        identity=platform_identity(candidate.get('source_url',''));exact=[];names=[]
        for row in db.execute('SELECT data FROM tasks'):
            task=task_defaults(json.loads(row['data']))
            if task.get('merged_into') or task.get('excluded_reason'):continue
            identities=self._task_platform_identities(db,task)
            if not self._compatible_identities(candidate,identities):continue
            if identity and identities:
                if identity in identities:exact.append(task)
            elif name_key(task)==name_key(candidate):names.append(task)
        return exact or names
    def _match(self, db, candidate):
        matches=self._matching_tasks(db,candidate)
        return matches[0] if len(matches)==1 and len(self._task_platform_identities(db,matches[0]))<=1 else None
    def _duplicate_review(self,db,candidate):
        from .task_identity import possible_duplicate,platform_identity
        reviews=[];candidate_id=platform_identity(candidate.get('source_url',''))
        exact=self._match(db,candidate)
        for row in db.execute('SELECT data FROM tasks'):
            task=task_defaults(json.loads(row['data']))
            if task.get('merged_into') or task.get('excluded_reason'):continue
            identities=self._task_platform_identities(db,task)
            if not self._compatible_identities(candidate,identities):continue
            if len(identities)>1:
                suspicious=candidate_id in identities or possible_duplicate(candidate,task)
                reason='conflicting_identity'
            else:
                if exact and exact['id']==task['id']:continue
                if candidate_id and identities and candidate_id not in identities:continue
                suspicious=possible_duplicate(candidate,task);reason='possible_duplicate'
            if suspicious:reviews.append(dict(task_id=task['id'],title=task['title'],course=task['course'],scope=task['scope'],version=task['version'],reason=reason))
        return reviews
    @staticmethod
    def _proposal_source_ids(db,proposal_id):
        return [row['message_id'] for row in db.execute('SELECT message_id FROM proposal_sources WHERE proposal_id=?',(proposal_id,))]
    def _proposal_identities(self,db,proposal):
        from .task_identity import platform_identity
        identity=platform_identity(proposal['candidate'].get('source_url',''));identities={identity} if identity else set()
        identities.update(proposal.get('identity_sources',{}))
        for row in db.execute('SELECT m.data FROM messages m JOIN proposal_sources s ON m.id=s.message_id WHERE s.proposal_id=?',(proposal['id'],)):
            external=json.loads(row['data']).get('external',{})
            identity=platform_identity(external.get('url','')) if external.get('kind')=='task_center' else ''
            if identity:identities.add(identity)
        return identities
    def _proposal_identity_hints(self,db,proposal):
        from .task_identity import identity_parts
        hints=list(proposal.get('identity_hints',[]))
        hints.append(identity_parts(proposal['candidate'].get('source_url','')))
        hints.extend(identity_parts(item['url']) for item in proposal.get('identity_sources',{}).values())
        for row in db.execute('SELECT m.data FROM messages m JOIN proposal_sources s ON m.id=s.message_id WHERE s.proposal_id=?',(proposal['id'],)):
            external=json.loads(row['data']).get('external',{})
            if external.get('kind')=='task_center':hints.append(identity_parts(external.get('url','')))
        return [hint for hint in hints if any(hint.get(key) for key in ('course','group','kind','number','problem'))]
    def _same_proposal_task(self,db,candidate,proposal):
        from .task_identity import name_key,platform_identity,identity_parts,compatible_parts
        parts=identity_parts(candidate.get('source_url',''))
        if any(not compatible_parts(parts,hint) for hint in self._proposal_identity_hints(db,proposal)):return False
        identity=platform_identity(candidate.get('source_url',''));identities=self._proposal_identities(db,proposal)
        return identities=={identity} if identity and identities else name_key(candidate)==name_key(proposal['candidate'])
    def _retain_proposal_sources(self,db,proposal,previous):
        for message_id in self._proposal_source_ids(db,previous['id']):
            db.execute('INSERT OR IGNORE INTO proposal_sources VALUES(?,?)',(proposal['id'],message_id))
        proposal.setdefault('identity_sources',{}).update(previous.get('identity_sources',{}))
        hints=proposal.setdefault('identity_hints',[])
        for hint in self._proposal_identity_hints(db,previous):
            safe={key:hint[key] for key in ('course','group','kind','number') if hint.get(key)}
            if safe and safe not in hints:hints.append(safe)
        proposal['source_message_ids']=self._proposal_source_ids(db,proposal['id'])
        proposal['source_count']=len(proposal['source_message_ids'])
        db.execute('UPDATE proposals SET data=? WHERE id=?',(dump(proposal),proposal['id']))
    def _replace_source_proposals(self,db,message,candidates,automatic,include_archived=False):
        statuses=('pending','archived') if include_archived else ('pending',)
        previous=[self._unpack_proposal(row) for row in db.execute("SELECT DISTINCT p.* FROM proposals p LEFT JOIN proposal_sources s ON s.proposal_id=p.id WHERE p.message_id=? OR s.message_id=?",(message['id'],message['id'])) if row['status'] in statuses]
        checkin_target=None
        if message.get('external',{}).get('kind')=='checkin_activity':
            targets={task['id'] for old in previous for task in [self._checkin_target(db,old,message,old['candidate'])] if task}
            if len(targets)!=1:raise Conflict('签到原始来源关联不明确，不能刷新为新任务，请核对原文。')
            checkin_target=next(iter(targets))
        protected=[]
        current_supplement=db.execute('SELECT rowid FROM message_supplements WHERE message_id=?',(message['id'],)).fetchone()
        for proposal in previous:
            newer=db.execute('SELECT 1 FROM message_supplements s JOIN proposal_sources ps ON ps.message_id=s.message_id WHERE ps.proposal_id=? AND s.rowid>? LIMIT 1',(proposal['id'],current_supplement['rowid'] if current_supplement else 0)).fetchone()
            if newer:protected.append(proposal)
        previous=[proposal for proposal in previous if proposal not in protected]
        db.executemany("UPDATE proposals SET status='dismissed' WHERE id=?",[(p['id'],) for p in previous])
        proposals=list(protected)
        fields=('operation','kind','deadline','requirements','submission_method','teacher')
        for candidate in candidates:
            checked=validate_candidate(candidate,message);source=message
            if any(self._same_proposal_task(db,checked,proposal) for proposal in protected):continue
            for old in previous:
                if not self._same_proposal_task(db,checked,old) or any(checked.get(key)!=old['candidate'].get(key) for key in fields):continue
                prior_message=json.loads(db.execute('SELECT data FROM messages WHERE id=?',(old['message_id'],)).fetchone()['data'])
                from .time_evidence import newer
                if newer(db,prior_message,source):
                    source=prior_message
                    candidate=old['candidate']
            proposals.append(self._proposal(db,candidate,source,automatic=automatic,target_override=checkin_target))
        for proposal in proposals:
            for old in previous:
                if self._same_proposal_task(db,proposal['candidate'],old):self._retain_proposal_sources(db,proposal,old)
        return proposals
    def _equivalent_pending(self,db,candidate,message,target,action):
        if message.get('supplement'):return None
        fields=('operation','kind','deadline','requirements','submission_method','teacher')
        for row in db.execute("SELECT * FROM proposals WHERE status='pending' ORDER BY rowid"):
            proposal=self._unpack_proposal(row);other=proposal['candidate']
            if candidate.get('relative_deadline',{}).get('event_key')!=other.get('relative_deadline',{}).get('event_key'):continue
            if proposal.get('target_id')!=(target['id'] if target else None) or proposal.get('expected_version')!=(target['version'] if target else None) or proposal['action']!=action:continue
            if any(candidate.get(key)!=other.get(key) for key in fields):continue
            if db.execute('SELECT 1 FROM message_supplements s JOIN proposal_sources ps ON ps.message_id=s.message_id WHERE ps.proposal_id=? LIMIT 1',(proposal['id'],)).fetchone():continue
            same=self._same_proposal_task(db,candidate,proposal)
            if not self._proposal_identities(db,proposal) and not (candidate.get('matchable') and other.get('matchable') or proposal['message_id']==message['id']):same=False
            if same:return proposal
        return None
    @staticmethod
    def _effective_action(target,candidate):
        if not target: return 'create'
        if candidate['operation']=='cancel': return 'cancel'
        if candidate['operation']=='update': return 'update'
        conflicts=(candidate['deadline'] and target['deadline'] and candidate['deadline']!=target['deadline']) or (candidate['submission_method'] and target['submission_method'] and candidate['submission_method']!=target['submission_method']) or candidate['kind']!=target['kind']
        return 'conflict' if conflicts else 'merge'
    def _proposal(self, db, candidate, message, automatic=True, target_override=None):
        from .intake_policy import automatic_candidate,archive_reason,is_reminder_notice
        if automatic:candidate=automatic_candidate(candidate,message)
        from .relative_deadlines import resolve
        candidate=resolve(self,db,candidate,message)
        c = validate_candidate(candidate, message)
        reminder=is_reminder_notice(c,message)
        target = None if reminder else self._match(db, c)
        if target_override is not None:
            if reminder or c['operation']!='update':raise ValidationError('签到截止更新只能修改已关联的原任务。')
            target=self._task(db,target_override)
            if any(normalize(c[key])!=normalize(target[key]) for key in ('course','scope','title')):
                raise Conflict('签到活动与原任务的课程或名称不一致，不能更新。')
        warnings = list(c['warnings'])
        if len(self._matching_tasks(db,c))>1:
            warnings.append('存在多个同课程、同班级的同名任务，需核对平台任务编号，不能自动选择或再创建副本。')
        action = 'create' if reminder else 'update' if c['operation']=='update' else self._effective_action(target,c)
        if target:
            if action=='conflict':
                warnings.append('同一任务出现字段冲突，请在冲突处理中明确选择保留当前值或采用新消息。')
            from .time_evidence import older
            if older(db,message,target,c) and action not in ('link','merge'):
                warnings.append('消息比当前任务来源更早，确认时将阻止覆盖，请查看最新通知。')
        else:
            if c['operation']=='cancel':
                warnings.append('未找到同课程、同班级的原任务，请核对任务名称。')
            elif c['operation']=='update':
                warnings.append('未匹配到原任务；更正任务名称、课程和班级后才能确认变更，不能将此通知新建成作业。')
        c['warnings'] = warnings
        conflicts={}
        if target and action=='conflict':
            for name in ('deadline','submission_method','kind'):
                if c.get(name) and target.get(name) and c[name]!=target[name]:conflicts[name]=dict(current=target[name],incoming=c[name])
        reason='reminder_only' if reminder else archive_reason(c,message,message.get('received_at') or now_iso()) if automatic and not target else ''
        if not reason:
            existing=self._equivalent_pending(db,c,message,target,action)
            if existing:
                from .task_identity import platform_identity,identity_parts
                identity=platform_identity(c.get('source_url',''))
                if identity:existing.setdefault('identity_sources',{})[identity]=dict(url=c['source_url'],message_id=message['id'])
                hints=existing.setdefault('identity_hints',[])
                for hint in (identity_parts(existing['candidate'].get('source_url','')),identity_parts(c.get('source_url',''))):
                    safe={key:hint[key] for key in ('course','group','kind','number') if hint.get(key)}
                    if safe and safe not in hints:hints.append(safe)
                prior_message=json.loads(db.execute('SELECT data FROM messages WHERE id=?',(existing['message_id'],)).fetchone()['data'])
                from .time_evidence import newer
                if newer(db,message,prior_message):
                    existing.update(message_id=message['id'],candidate=c,conflicts=conflicts,before=target,duplicate_review=self._duplicate_review(db,c))
                db.execute('INSERT OR IGNORE INTO proposal_sources VALUES(?,?)',(existing['id'],message['id']))
                existing['source_count']=len(self._proposal_source_ids(db,existing['id']))
                existing['source_message_ids']=self._proposal_source_ids(db,existing['id'])
                db.execute('UPDATE proposals SET message_id=?,data=? WHERE id=?',(existing['message_id'],dump(existing),existing['id']))
                return existing
        reviews=self._duplicate_review(db,c)
        if target_override is not None and target:
            reviews=[item for item in reviews if item['task_id']!=target['id']]
        if reviews:c['warnings'].append('存在疑似重复或身份不明确的任务，请核对来源；不能直接再创建一项。')
        p = dict(id=uuid.uuid4().hex, message_id=message['id'], candidate=c, action=action,conflicts=conflicts,
                 target_id=target['id'] if target else None, expected_version=target['version'] if target else None,
                 before=target, status='archived' if reason else 'pending', created_at=now_iso(),archive_reason=reason,manual_review=not automatic,duplicate_review=reviews,source_count=1,source_message_ids=[message['id']])
        from .task_identity import platform_identity
        identity=platform_identity(c.get('source_url',''))
        p['identity_sources']={identity:dict(url=c['source_url'],message_id=message['id'])} if identity else {}
        db.execute('INSERT INTO proposals(id,message_id,data,status) VALUES(?,?,?,?)', (p['id'], message['id'], dump(p),p['status']))
        db.execute('INSERT INTO proposal_sources VALUES(?,?)',(p['id'],message['id']))
        return p
    def reconcile_automatic_drafts(self):
        """Archive old automatic creates, preserving evidence and explicit user decisions."""
        from .intake_policy import automatic_candidate,archive_reason,is_automatic_message,is_reminder_notice
        count=0
        with self.lock,self.connection() as db:
            rows=db.execute("SELECT p.id,p.data,m.data AS message_data FROM proposals p JOIN messages m ON m.id=p.message_id WHERE p.status='pending'").fetchall()
            for row in rows:
                proposal=json.loads(row['data']);message=json.loads(row['message_data'])
                if is_reminder_notice(proposal['candidate'],message):
                    proposal.update(status='archived',archive_reason='reminder_only')
                    db.execute("UPDATE proposals SET data=?,status='archived' WHERE id=?",(dump(proposal),row['id']));count+=1;continue
                if proposal.get('manual_review') or message.get('last_analyzed_at') or proposal.get('action')!='create' or proposal.get('target_id') or not is_automatic_message(message):continue
                candidate=automatic_candidate(proposal['candidate'],message)
                if self._match(db,candidate):continue
                reason=archive_reason(candidate,message,message.get('received_at') or proposal.get('created_at') or now_iso())
                if candidate==proposal['candidate'] and not reason:continue
                proposal.update(candidate=candidate,archive_reason=reason)
                status='archived' if reason else 'pending';proposal['status']=status
                db.execute('UPDATE proposals SET data=?,status=? WHERE id=?',(dump(proposal),status,row['id']))
                count+=bool(reason)
        return count
    def ingest_checkin_activity(self, normalized):
        """Turn a uniquely matched read-only sign-in end time into an update draft."""
        external=normalized['external'];title=external['title'];scope=normalized['scope']
        from .task_identity import normalized as normalize_name
        published=parse_timestamp(external['published_at'])
        matches=[]
        with self.lock,self.connection() as db:
            for row in db.execute('SELECT id,data FROM messages WHERE hidden_at IS NULL'):
                message=json.loads(row['data']);origin=message.get('external',{})
                if origin.get('platform')!='chaoxing-web' or origin.get('kind','chat')!='chat':continue
                if origin.get('direction','received')!='received' or origin.get('conversation')!=scope:continue
                if normalize_name(message.get('text',''))!=normalize_name(title):continue
                try:posted=parse_timestamp(message['captured_at'])
                except (KeyError,ValidationError):continue
                if abs((posted-published).total_seconds())<=120:matches.append(message)
            if len(matches)!=1:
                return dict(message=None,proposals=[],duplicate=True,deferred=True,mode='rules',trace=[])
            source_message=matches[0]
            external['chat_source_id']=source_message['id']
            if not external.get('deadline') or external.get('activity_state')=='ended':
                return self.ingest(text=normalized['text'],source=normalized['source'],captured_at=normalized['captured_at'],course=normalized['course'],scope=scope,candidates=[],mode='rules',external=external)
            task_ids={row['task_id'] for row in db.execute('SELECT task_id FROM sources WHERE message_id=?',(source_message['id'],))}
            tasks=[]
            for task_id in task_ids:
                try:tasks.append(self._task(db,task_id))
                except (NotFound,Conflict):continue
            if len(tasks)!=1:
                if not tasks:
                    # Keep verified evidence before task confirmation; no new draft.
                    return self.ingest(text=normalized['text'],source=normalized['source'],captured_at=normalized['captured_at'],course=normalized['course'],scope=scope,candidates=[],mode='rules',external=external)
                return dict(message=None,proposals=[],duplicate=True,deferred=True,mode='rules',trace=[])
            task=tasks[0]
            if (normalize_name(task['title'])!=normalize_name(title) or task['scope']!=scope or
                    task['status']!='pending' or task.get('merged_into') or task.get('excluded_reason')):
                return dict(message=None,proposals=[],duplicate=True,deferred=True,mode='rules',trace=[])
            from .task_identity import identity_parts,platform_identity
            parts=identity_parts(task.get('source_url',''))
            if ((parts.get('course') and parts['course']!=external['course_id']) or
                    (parts.get('group') and parts['group']!=external['class_id'])):
                return dict(message=None,proposals=[],duplicate=True,deferred=True,mode='rules',trace=[])
            external['chat_source_id']=source_message['id']
            candidate=dict(normalized['candidates'][0])
            candidate.update(title=task['title'],course=task['course'],scope=task['scope'],kind=task['kind'],
                             submission_method=task.get('submission_method',''),teacher=task.get('teacher',''),
                             source_url=task.get('source_url',''),platform_status=task.get('platform_status',''),
                             confidence='high',field_evidence=external.get('field_evidence',{}))
            if platform_identity(candidate.get('source_url','')):
                candidate_matches=self._matching_tasks(db,candidate);matched=self._match(db,candidate)
                if len(candidate_matches)!=1 or not matched or matched['id']!=task['id']:
                    return dict(message=None,proposals=[],duplicate=True,deferred=True,mode='rules',trace=[])
            try:current=parse_timestamp(task['deadline']) if task.get('deadline') else None
            except ValidationError:current=None
            incoming=parse_timestamp(external['deadline'])
            if current==incoming:
                return dict(message=dict(id=external['message_id'],external=external),proposals=[],duplicate=True,ignored=True,mode='rules',trace=[])
        return self.ingest(text=normalized['text'],source=normalized['source'],captured_at=normalized['captured_at'],
                           course=task['course'],scope=task['scope'],candidates=[candidate],mode='rules',trace=[],external=external,
                           _target_task_id=task['id'])

    def ingest(self, text, source='手动导入', captured_at=None, course='', scope='', event_key=None, sample=False, candidates=None, mode='rules', trace=None, external=None, _target_task_id=None, _chat_import=None):
        text = clean_string(text, '消息', 30000, True)
        source = clean_string(source, '来源', 120, True)
        course, scope = clean_string(course, '课程', 100), clean_string(scope, '班级', 100)
        at = parse_timestamp(captured_at or now_iso()).replace(microsecond=0).isoformat()
        if event_key is not None:
            event_key = clean_string(event_key, '通知标识', 1000, True)
        identity = [text,source,course,scope,event_key,at[:10]]
        if _chat_import is not None:
            identity=[source,'chat-import',text,course,_chat_import]
        if external is not None:
            if not isinstance(external, dict) or external.get('platform') != 'chaoxing-web':
                raise ValidationError('外部消息来源无效。')
            identity = [source, 'chaoxing-web', clean_string(external.get('message_id'), '网页消息编号', 200, True)]
        fingerprint = hashlib.sha256(dump(identity).encode()).hexdigest()
        from .message_capture import capture_key
        content_key=capture_key(external,course,scope,text)
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT data,capture_key FROM messages WHERE fingerprint=?', (fingerprint,)).fetchone()
            if not old and content_key:
                old=db.execute('SELECT data,capture_key FROM messages WHERE capture_key=? ORDER BY rowid DESC LIMIT 1',(content_key,)).fetchone()
            cleared=db.execute('SELECT message_id FROM cleared_messages WHERE fingerprint IN (?,?)',(fingerprint,content_key)).fetchone()
            if cleared and not old:
                message=dict(id=cleared['message_id'],text='',source=source,course=course,scope=scope,captured_at=at,received_at=now_iso(),sample=bool(sample),mode=mode,trace=[])
                if external is not None:message['external']=external
                return dict(message=message,proposals=[],duplicate=True,cleared=True,mode=mode,trace=[])
            same_platform_content=False
            if external and external.get('kind')=='task_center':
                from .platform_check import observe,signature
                previous=json.loads(old['data']) if old else None
                # An identifier replay with changed payload is not new evidence.
                prior=previous.get('external',{}) if previous else {}
                # Legacy source records omitted description/attachments. The raw
                # body and all previously stored fields must still match exactly.
                prior_payload={**external,**prior}
                same_payload=previous and ((content_key and old['capture_key']==content_key) or (previous['text']==text and previous['course']==course and previous['scope']==scope and signature(prior_payload)==signature(external) and all(prior.get(k)==external.get(k) for k in ('url','platform_status'))))
                if not previous or same_payload:
                    observed_at=parse_timestamp(captured_at or at).isoformat()
                    same_platform_content=observe(db,external,course,scope,observed_at,now_iso())
                if same_payload and external.get('published_at') and not prior.get('published_at'):
                    previous['external']={**prior,'published_at':external['published_at'],'field_evidence':{**prior.get('field_evidence',{}),**({'published_at':external['field_evidence']['published_at']} if external.get('field_evidence',{}).get('published_at') else {})}}
                    db.execute('UPDATE messages SET data=? WHERE id=?',(dump(previous),previous['id']))
                    old=db.execute('SELECT data,capture_key FROM messages WHERE id=?',(previous['id'],)).fetchone()
            if old:
                m = json.loads(old['data'])
                task_conflict=False
                if external and external.get('kind')=='task_center' and m['course']==course and m['scope']==scope and not cleared:
                    from .chaoxing import merge_task_attachments,task_payload,normalize_web_message
                    enriched,task_conflict=merge_task_attachments(m.get('external',{}),external,course,scope)
                    if enriched:
                        value=normalize_web_message(task_payload(enriched,course,scope,m['captured_at']))
                        m.update(external=value['external'],text=value['text'],last_attachment_read_at=now_iso())
                        updated_key=capture_key(m['external'],course,scope,m['text'])
                        db.execute('UPDATE messages SET data=?,capture_key=? WHERE id=?',(dump(m),updated_key,m['id']))
                        states={r['status'] for r in db.execute('SELECT p.status FROM proposals p LEFT JOIN proposal_sources s ON p.id=s.proposal_id WHERE p.message_id=? OR s.message_id=?',(m['id'],m['id']))}
                        proposals=self._replace_source_proposals(db,m,value['candidates'],automatic=not bool(m.get('last_analyzed_at'))) if 'pending' in states or 'confirmed' in states or not states else []
                        return dict(message=m,proposals=proposals,duplicate=True,enriched=True,mode=m['mode'],trace=m.get('trace',[]))
                if external and external.get('kind')=='course_notice' and m['course']==course and m['scope']==scope and (m['captured_at']==at or external.get('time_known') is False):
                    from .chaoxing import merge_notice_attachments,notice_text,parse_notice_candidates,absolute_candidates
                    enriched=merge_notice_attachments(m.get('external',{}),external)
                    if enriched:
                        m['external']=enriched;m['text']=notice_text(enriched);m['last_attachment_read_at']=now_iso()
                        parsed=parse_notice_candidates(enriched,m['captured_at'],course,scope) if enriched['time_known'] else absolute_candidates(m)
                        db.execute('UPDATE messages SET data=?,sort_at=? WHERE id=?',(dump(m),self._message_time(m),m['id']))
                        proposals=self._replace_source_proposals(db,m,parsed,automatic=not bool(m.get('last_analyzed_at')))
                        return dict(message=m,proposals=proposals,duplicate=True,enriched=True,mode=m['mode'],trace=m.get('trace',[]))
                conflict=task_conflict
                if external and external.get('kind')=='course_notice':
                    previous=m.get('external',{}).get('attachments',[]);incoming=external.get('attachments',[])
                    conflict=any(old.get('status')=='partial' and new.get('status')=='extracted' and (old.get('name'),old.get('url'))==(new.get('name'),new.get('url')) and not new.get('text','').startswith(old.get('text','')) for old,new in zip(previous,incoming))
                ps = [self._unpack_proposal(row) for row in db.execute('SELECT DISTINCT p.* FROM proposals p LEFT JOIN proposal_sources s ON s.proposal_id=p.id WHERE p.message_id=? OR s.message_id=?', (m['id'],m['id']))]
                return dict(message=m, proposals=ps, duplicate=True, cleared=bool(cleared), attachment_conflict=conflict, mode=m['mode'], trace=m.get('trace', []))
            m = dict(id=uuid.uuid4().hex, text=text, source=source, course=course, scope=scope, captured_at=at,
                     received_at=now_iso(), sample=bool(sample), mode=mode, trace=trace or [])
            if external is not None: m['external'] = external
            if _chat_import is not None:m['chat_import']=dict(_chat_import)
            parsed = parse_message(text, at, course, scope) if candidates is None else candidates
            if same_platform_content: parsed=[]
            if not isinstance(parsed, list) or len(parsed) > 20:
                raise ValidationError('每条消息最多包含 20 个任务草稿。')
            db.execute('INSERT INTO messages(id,fingerprint,data,sort_at,capture_key) VALUES(?,?,?,?,?)', (m['id'], fingerprint, dump(m),self._message_time(m),content_key))
            proposals = [self._proposal(db, c, m,target_override=_target_task_id) for c in parsed]
            return dict(message=m, proposals=proposals, duplicate=False, mode=mode, trace=m['trace'])
    def supplement_context(self,message_id):
        from .supplements import context
        with self.connection() as db:return context(self,db,message_id)
    def supplement_message(self,message_id,body):
        from .supplements import submit
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return submit(self,db,message_id,body)
    def retry_task_extraction(self,message_id):
        """Retry failed automatic extraction; respect archived/ignored/cleared evidence."""
        from .chaoxing import normalize_web_message
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data,capture_key FROM messages WHERE id=?',(message_id,)).fetchone()
            if not row:return []
            if db.execute('SELECT 1 FROM cleared_messages WHERE message_id=?',(message_id,)).fetchone():return []
            if db.execute('SELECT 1 FROM proposals WHERE message_id=? UNION SELECT 1 FROM proposal_sources WHERE message_id=?',(message_id,message_id)).fetchone():return []
            message=json.loads(row['data']);external=message.get('external',{})
            if external.get('kind') not in ('task_center','checkin_activity'):return []
            fields=('kind','message_id','title','url','task_type','deadline','published_at','submission_method','platform_status','teacher','field_evidence','description','attachments','detail_state','detail_error','media_pending_count','conversation','sender','display_time','direction','activity_id','course_id','class_id','chat_source_id')
            body={key:external[key] for key in fields if key in external}
            body.update(text=message['text'],course=message['course'],captured_at=message['captured_at'])
            candidates=normalize_web_message(body)['candidates']
            proposals=self._replace_source_proposals(db,message,candidates,automatic=True)
            if proposals and external.get('extraction_warning'):
                external.pop('extraction_warning',None)
                db.execute('UPDATE messages SET data=? WHERE id=?',(dump(message),message_id))
            return proposals
    def reanalyze(self, message_id):
        """Explicit rule re-extraction; preserve source identity and original posted time."""
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM messages WHERE id=?',(message_id,)).fetchone()
            if not row: raise NotFound('消息不存在。')
            m=json.loads(row['data'])
            unknown_publication=m.get('external',{}).get('time_known') is False
            from .checkin_evidence import is_checkin
            if m.get('chat_import'):
                from .chat_import import candidates as chat_candidates
                candidates=chat_candidates(m['text'],m['chat_import'].get('published_at'),m['course'],m['scope'])
            elif unknown_publication:
                from .chaoxing import absolute_candidates
                candidates=absolute_candidates(m)
                if not candidates:raise ValidationError('网页发布时间尚未识别，无法推算相对日期；请补充真实发布时间或明确的完整截止日期。')
            elif m.get('supplement'):
                from .supplements import candidates_for,retain_original
                candidates=candidates_for(self,db,m)
            elif is_checkin(m):
                from .chaoxing import checkin_card_candidates
                candidates=checkin_card_candidates(m)
            elif m.get('external',{}).get('kind')=='course_notice':
                from .chaoxing import parse_notice_candidates
                candidates=parse_notice_candidates(m['external'],m['captured_at'],m['course'],m['scope'])
            elif m.get('external',{}).get('kind') in ('task_center','checkin_activity'):
                from .chaoxing import normalize_web_message
                allowed={'kind','message_id','title','url','task_type','deadline','published_at','submission_method','platform_status','teacher','field_evidence','description','attachments','detail_state','detail_error','media_pending_count','activity_id','course_id','class_id','chat_source_id'}
                body={key:value for key,value in m['external'].items() if key in allowed}
                body.update(text=m['text'],course=m['course'],conversation=m['scope'],captured_at=m['captured_at'])
                candidates=normalize_web_message(body)['candidates']
            else:
                candidates=parse_message(m['text'],m['captured_at'],m['course'],m['scope'])
            m.setdefault('previous_analyses',[]).append(dict(mode=m['mode'],trace=m.get('trace',[]),at=m.get('last_analyzed_at',m['received_at'])))
            m['mode'],m['trace'],m['last_analyzed_at']='rules',[],now_iso()
            db.execute('UPDATE messages SET data=? WHERE id=?',(dump(m),message_id))
            proposals=self._replace_source_proposals(db,m,candidates,automatic=False,include_archived=True)
            if m.get('supplement'):
                for proposal in proposals:retain_original(self,db,proposal,m['supplement']['original_message_id'])
            return dict(message=m,proposals=proposals,mode='rules',trace=[],reanalyzed=True,duplicate=True)
    @staticmethod
    def _unpack_proposal(row):
        p = json.loads(row['data'])
        p['status'], p['task_id'] = row['status'], row['task_id']
        return p
    def proposals(self, status='pending'):
        with self.connection() as db:
            sql, args = ('SELECT * FROM proposals WHERE status=? ORDER BY rowid DESC', (status,)) if status else ('SELECT * FROM proposals ORDER BY rowid DESC', ())
            proposals=[self._unpack_proposal(r) for r in db.execute(sql, args)]
            from .time_evidence import proposal_view
            return [proposal_view(self,db,p) for p in proposals]
    def messages(self, limit=500, offset=0, include_hidden=False):
        with self.connection() as db:
            where='' if include_hidden else 'WHERE hidden_at IS NULL'
            sql=f'SELECT data FROM messages {where} ORDER BY sort_at DESC,rowid DESC'
            if limit is not None:
                sql+=' LIMIT ? OFFSET ?';args=(limit,offset)
            else:args=()
            return [json.loads(r['data']) for r in db.execute(sql,args)]
    def message_page(self,limit=50,offset=0,deadline_from='',deadline_to=''):
        if type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or offset<0:
            raise ValidationError('消息分页参数无效。')
        for bound in (deadline_from,deadline_to):
            if not isinstance(bound,str):raise ValidationError('截止日期格式无效。')
            if bound:
                try:
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',bound):raise ValueError
                    date.fromisoformat(bound)
                except ValueError:raise ValidationError('截止日期格式无效。') from None
        if deadline_from and deadline_to and deadline_from>deadline_to:raise ValidationError('起始日期不能晚于结束日期。')
        items=self.message_feed(limit=None);unfiltered_total=len(items)
        if deadline_from or deadline_to:
            def matches(message):
                value=message.get('timing',{}).get('deadline')
                if not value:return False
                day=value if len(value)==10 else parse_timestamp(value).date().isoformat()
                return (not deadline_from or day>=deadline_from) and (not deadline_to or day<=deadline_to)
            items=[message for message in items if matches(message)]
        return dict(items=items[offset:offset+limit],total=len(items),unfiltered_total=unfiltered_total,limit=limit,offset=offset)
    def message_feed(self,limit=500,offset=0):
        from .message_timing import annotate,date_key
        with self.connection() as db:
            db.execute('BEGIN')
            messages=[json.loads(row['data']) for row in db.execute('SELECT data FROM messages WHERE hidden_at IS NULL ORDER BY rowid DESC')]
            items=annotate(self,db,messages)
        items.sort(key=lambda m:(date_key(m['timing']['published_at']),m.get('external',{}).get('title',''),m['id']),reverse=True)
        return items[offset:] if limit is None else items[offset:offset+limit]
    def message_display(self,message_id):
        from .message_timing import annotate
        with self.connection() as db:
            db.execute('BEGIN')
            row=db.execute('SELECT data FROM messages WHERE id=?',(message_id,)).fetchone()
            if not row:raise NotFound('消息不存在或已清理。')
            result=annotate(self,db,[json.loads(row['data'])])[0]
            tasks=[]
            for row in db.execute('SELECT DISTINCT t.data FROM tasks t JOIN sources s ON s.task_id=t.id WHERE s.message_id=?',(message_id,)):
                task=json.loads(row['data'])
                if task.get('merged_into') or task.get('excluded_reason'):continue
                tasks.append({key:task.get(key) for key in ('id','title','course','scope','deadline','status')})
            proposals=[]
            rows=db.execute("SELECT DISTINCT p.* FROM proposals p LEFT JOIN proposal_sources s ON s.proposal_id=p.id WHERE (p.message_id=? OR s.message_id=?) AND p.status IN ('pending','archived','dismissed') ORDER BY p.rowid DESC",(message_id,message_id))
            for row in rows:
                proposal=self._unpack_proposal(row);candidate=proposal['candidate']
                proposals.append(dict(id=proposal['id'],status=proposal['status'],action=proposal['action'],**{key:candidate.get(key) for key in ('title','course','deadline')}))
            result['related']=dict(tasks=tasks,proposals=proposals)
            return result
    def message(self,message_id):
        with self.connection() as db:
            row=db.execute('SELECT data FROM messages WHERE id=?',(message_id,)).fetchone()
            if not row:raise NotFound('消息不存在或已清理。')
            return json.loads(row['data'])
    def cleanup_preview(self):
        with self.connection() as db:
            ids=[row['id'] for row in db.execute('SELECT id FROM messages WHERE hidden_at IS NULL ORDER BY sort_at DESC,rowid DESC LIMIT 10000')]
            total=db.execute('SELECT COUNT(*) FROM messages WHERE hidden_at IS NULL').fetchone()[0]
        return dict(ids=ids,count=len(ids),total=total)
    def clear_messages(self,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=10000 or any(not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value) for value in ids):
            raise ValidationError('请选择最多 10000 条有效消息。')
        cleared=preserved=deleted=0
        with self.lock,self.connection() as db:
            for message_id in dict.fromkeys(ids):
                row=db.execute('SELECT fingerprint,capture_key FROM messages WHERE id=? AND hidden_at IS NULL',(message_id,)).fetchone()
                if not row:continue
                keep=db.execute('SELECT 1 FROM sources WHERE message_id=? LIMIT 1',(message_id,)).fetchone() or db.execute("SELECT 1 FROM proposals WHERE message_id=? AND (status='pending' OR task_id IS NOT NULL) LIMIT 1",(message_id,)).fetchone() or db.execute("SELECT 1 FROM proposal_sources s JOIN proposals p ON p.id=s.proposal_id WHERE s.message_id=? AND (p.status='pending' OR p.task_id IS NOT NULL) LIMIT 1",(message_id,)).fetchone()
                db.execute('INSERT OR REPLACE INTO cleared_messages VALUES(?,?,?)',(row['fingerprint'],message_id,now_iso()))
                if row['capture_key']:db.execute('INSERT OR REPLACE INTO cleared_messages VALUES(?,?,?)',(row['capture_key'],message_id,now_iso()))
                if keep:
                    db.execute('UPDATE messages SET hidden_at=? WHERE id=?',(now_iso(),message_id));preserved+=1
                else:
                    db.execute('DELETE FROM proposal_sources WHERE message_id=? OR proposal_id IN (SELECT id FROM proposals WHERE message_id=?)',(message_id,message_id))
                    db.execute('DELETE FROM proposals WHERE message_id=?',(message_id,))
                    db.execute('DELETE FROM messages WHERE id=?',(message_id,));deleted+=1
                cleared+=1
        return dict(cleared=cleared,preserved=preserved,deleted=deleted)
    def tasks(self, course='', scope=None):
        with self.connection() as db:
            items = [task_defaults(json.loads(r['data'])) for r in db.execute('SELECT data FROM tasks ORDER BY rowid DESC')]
            from .platform_check import read
            items=[task for task in items if not task.get('merged_into') and not task.get('excluded_reason')]
            from .checkin_evidence import task_verification
            for task in items:
                task['platform_check']=read(db,task)
                checkin_state=task_verification(db,task)
                if checkin_state:task['checkin_verification']=checkin_state
        return sorted([x for x in items if (not course or normalize(x['course']) == normalize(course)) and (scope is None or normalize(x['scope']) == normalize(scope))], key=lambda x:(x['status'] in ('submitted','cancelled'), x['deadline'] or '9999', x['title']))
    def _save_task(self, db, task, key=None):
        if key is None:
            db.execute('UPDATE tasks SET data=?, version=? WHERE id=?', (dump(task),task['version'],task['id']))
        else:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?)', (task['id'],key,dump(task),task['version']))
    def _history(self, db, task, before, action, message_id=None):
        db.execute('INSERT INTO history(task_id,data) VALUES(?,?)', (task['id'],dump(dict(at=now_iso(),action=action,before=before,after=task,message_id=message_id))))
    def exclude_reminder_task(self,task_id,expected_version):
        """Explicit repair only: retain an unmodified false task and all evidence."""
        from .intake_policy import is_reminder_notice
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE');task=self._task(db,task_id)
            if type(expected_version) is not int or task['version']!=expected_version:raise Conflict('任务版本已变化，请重新核对。')
            if task.get('excluded_reason')=='reminder_only':return task
            messages=[json.loads(row['data']) for row in db.execute('SELECT m.data FROM sources s JOIN messages m ON m.id=s.message_id WHERE s.task_id=?',(task_id,))]
            title_is_reminder=re.fullmatch(r'(?:作业|任务|考试|测验)(?:即将)?(?:结束|截止|到期)提醒[：:！!。]?',task['title'])
            if task['version']!=1 or task['status']!='pending' or task['checklist'] or not title_is_reminder or self._task_platform_identities(db,task) or not messages or not all(is_reminder_notice({},message) for message in messages):
                raise Conflict('只可纠正完全由系统提醒误建、且尚未修改的记录；真实任务需人工核对。')
            before=dict(task);task.update(excluded_reason='reminder_only',excluded_at=now_iso(),updated_at=now_iso(),version=task['version']+1)
            self._save_task(db,task);db.execute('UPDATE tasks SET task_key=? WHERE id=?',('excluded:'+task_id,task_id))
            for row in db.execute('SELECT * FROM proposals WHERE task_id=?',(task_id,)).fetchall():
                proposal=self._unpack_proposal(row);proposal.update(status='archived',archive_reason='reminder_only',task_id=None)
                db.execute("UPDATE proposals SET status='archived',task_id=NULL,data=? WHERE id=?",(dump(proposal),row['id']))
            self._history(db,task,before,'reminder_misclassification_corrected',messages[0]['id'])
            return task
    def _checkin_target(self,db,proposal,message,candidate):
        """Only a verified original chat-source link authorizes sign-in updates."""
        external=message.get('external',{})
        if external.get('kind')!='checkin_activity' or not proposal.get('target_id'):return None
        try:target=self._task(db,proposal['target_id'])
        except (NotFound,Conflict):return None
        if target.get('excluded_reason') or candidate.get('operation')!='update':return None
        if any(normalize(candidate[key])!=normalize(target[key]) for key in ('course','scope','title')):return None
        source_id=external.get('chat_source_id','')
        if not source_id:return None
        for row in db.execute('SELECT task_id FROM sources WHERE message_id=?',(source_id,)):
            try:
                if self._task(db,row['task_id'])['id']==target['id']:return target
            except (NotFound,Conflict):pass
        return None
    def confirm(self, proposal_id, edits=None):
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM proposals WHERE id=?', (proposal_id,)).fetchone()
            if not row:
                raise NotFound('草稿不存在。')
            p = self._unpack_proposal(row)
            if p['status'] == 'confirmed':
                return self._task(db, p['task_id'])
            if p['status'] != 'pending':
                raise Conflict('草稿已忽略。')
            from .time_evidence import proposal_view,older,publication,task_publication
            p=proposal_view(self,db,p)
            message = json.loads(db.execute('SELECT data FROM messages WHERE id=?', (p['message_id'],)).fetchone()['data'])
            if not p.get('target_id') and p['candidate'].get('operation','create')=='create' and not (isinstance(edits,dict) and edits.get('link_only_to')):
                from .checkin_evidence import references as checkin_references,unique as unique_checkin
                refs=checkin_references(db,message)
                from .checkin_evidence import is_checkin,verification
                if is_checkin(message,db):
                    state=verification(db,message)
                    if state=='unverified':raise Conflict('签到详情尚未核验成功，不能创建待办。请同步学习通后重试；原消息和草稿保留。')
                    if state=='ended':raise Conflict('该场签到已经结束，不能创建待办；原消息保留。')
                    if state=='ambiguous':raise Conflict('签到活动身份或截止依据不唯一，请先核对原活动，不能创建待办。')
                if refs and not unique_checkin(refs):raise Conflict('签到活动身份或截止时间不唯一，请核对原活动，不能直接创建任务。')
                if refs and parse_timestamp(refs[0]['deadline'])<=parse_timestamp(now_iso()):raise Conflict('该场签到已经截止，不能新建为待办任务。原消息保留，可忽略草稿。')
            from .intake_policy import is_reminder_notice
            if is_reminder_notice(p['candidate'],message):raise Conflict('原文是已有作业的倒计时或状态提醒，不能新建任务；请重新提取归档。')
            resolution=None
            expected_version=None
            link_only_to=None
            if isinstance(edits,dict):
                edits=dict(edits)
                resolution=edits.pop('resolution',None)
                expected_version=edits.pop('expected_version',None)
                link_only_to=edits.pop('link_only_to',None)
                if expected_version is not None and (type(expected_version) is not int or expected_version<1):
                    raise ValidationError('任务版本无效。')
            c = validate_candidate(p['candidate'], message, edits)
            if c.get('deadline_basis',{}).get('deadline')!=c.get('deadline'):c.pop('deadline_basis',None)
            reviews=self._duplicate_review(db,c)
            checkin_target=self._checkin_target(db,p,message,c)
            if checkin_target:
                reviews=[item for item in reviews if item['task_id']!=checkin_target['id']]
            if link_only_to is not None:
                if not isinstance(link_only_to,str) or not any(item['task_id']==link_only_to and item['reason']!='conflicting_identity' for item in reviews):
                    raise Conflict('所选任务不属于当前疑似重复候选，请刷新核对。')
                target=self._task(db,link_only_to)
                if target['version']!=expected_version:raise Conflict('所选任务已更新，请刷新后重新核对。')
                task=dict(target,version=target['version']+1,updated_at=now_iso())
                self._save_task(db,task);self._attach_proposal_sources(db,p,task)
                self._claim_identities(db,task,c,self._proposal_identities(db,p))
                self._history(db,task,target,'duplicate_source_linked',message['id'])
                p.update(action='link',target_id=task['id'],before=target)
                db.execute("UPDATE proposals SET status='confirmed',task_id=?,data=? WHERE id=?",(task['id'],dump(p),p['id']))
                return task
            if reviews:raise Conflict('存在同名、疑似重复或冲突身份，请核对已有任务并关联原文，不能直接创建副本。')
            if c['operation']=='update' and expected_version is not None:
                c['matchable']=True
            if len(self._matching_tasks(db,c))>1:
                raise Conflict('存在多个同名任务，请先核对平台任务编号或处理已有重复记录，不能再创建副本。')
            target = self._match(db, c) or checkin_target
            if c['deadline_change_requested'] and not c['deadline']:
                raise ValidationError('没有识别到新的截止日期；请填写新日期后再确认变更。')
            if c['operation']=='update' and not target:
                raise Conflict('未匹配到原任务，截止变更不能创建新作业。请核对任务名称、课程和班级。')
            if p['target_id']:
                if any(normalize(c[key])!=normalize(p['candidate'][key]) for key in ('course','scope','title')):
                    raise Conflict('已匹配任务的课程、班级或名称不能在确认时改变，请重新提取后核对。')
                if not target or target['id'] != p['target_id']:
                    raise Conflict('更改课程、班级或名称会改变匹配结果，请忽略后重新导入。')
                if target['version'] != p['expected_version']:
                    raise Conflict('任务已被更新，本草稿版本已过期。请点击“刷新草稿”，或在消息记录中重新提取。')
                relative=c.get('relative_deadline',{})
                if relative.get('status')=='resolved' and (relative.get('task_id')!=target['id'] or relative.get('base_version')!=target['version'] or relative.get('base_deadline')!=target['deadline']):
                    raise Conflict('延期依据的原任务已变化，请重新提取并核对。')
                if relative.get('status')=='already_applied' and c.get('deadline')!=target.get('deadline'):
                    raise Conflict('该延期通知已应用，不能重复变更截止；请使用新的变更通知。')
            elif target:
                if c['operation']!='update':
                    raise Conflict('另一草稿已创建该任务，请刷新草稿后核对并关联来源。')
                if expected_version is None or target['version']!=expected_version:
                    raise Conflict('原任务已变化或未完成版本核对，请刷新后重新确认截止变更。')
            action = self._effective_action(target,c)
            if p.get('action') in ('link','merge') and edits and action=='conflict' and resolution is None:
                c['operation']='update';action='update'
            if action=='conflict' and resolution not in ('current','incoming'):
                raise ValidationError('冲突草稿必须明确选择保留当前值或采用新消息。')
            older_source=bool(target and older(db,message,target,c))
            if older_source and message.get('supplement') and action=='merge':
                if any(c.get(name) and c[name]!=target.get(name) for name in ('deadline','submission_method','teacher','source_url','platform_status')):
                    raise Conflict('补充依据早于任务最新来源，不能覆盖字段；请核对通知时间后重新补充。')
            if target and action not in ('link','merge') and not (action=='conflict' and resolution=='current') and older_source:
                raise Conflict('历史消息不能覆盖较新的已确认通知。')
            history_action='conflict_keep_current' if action=='conflict' and resolution=='current' else 'conflict_use_incoming' if action=='conflict' else 'merge_older_source' if action=='merge' and older_source else action
            p['action'] = history_action
            before = dict(target) if target else None
            if target:
                task = dict(target)
                if c['operation'] == 'cancel':
                    task['status'] = 'cancelled'
                elif action=='update' or (action=='conflict' and resolution=='incoming'):
                    task['kind']=c['kind']
                    if c['deadline']:
                        task['deadline'], task['date_precision'] = c['deadline'],c['date_precision']
                    if c['requirements']:
                        done = {x['text']:x['done'] for x in task['checklist']}
                        task['checklist'] = [dict(text=x,done=done.get(x,False)) for x in c['requirements']]
                    for name in ('submission_method','teacher','source_url','platform_status','confidence','field_evidence'):
                        if c.get(name) not in ('',{},None):task[name]=c[name]
                elif action=='merge' and (not older_source or message.get('supplement')):
                    done={x['text']:x['done'] for x in task['checklist']}
                    merged=list(done)
                    for requirement in c['requirements']:
                        if requirement not in done:merged.append(requirement)
                    task['checklist']=[dict(text=value,done=done.get(value,False)) for value in merged]
                    if not task['deadline'] and c['deadline']:task['deadline'],task['date_precision']=c['deadline'],c['date_precision']
                    for name in ('submission_method','teacher','source_url','platform_status'):
                        if not task.get(name) and c.get(name):task[name]=c[name]
                    if c['confidence']=='high':task['confidence']='high'
                    task['field_evidence']={**task.get('field_evidence',{}),**c.get('field_evidence',{})}
                elif action=='merge':
                    # A later list scan's unknown deadline is not evidence that
                    # an explicit published deadline was removed. Human review
                    # may fill the gap without restoring older requirements.
                    if not task['deadline'] and c['deadline'] and message.get('external',{}).get('kind')=='course_notice':
                        task['deadline'],task['date_precision']=c['deadline'],c['date_precision']
                    from .task_identity import platform_identity
                    if not task.get('source_url') and platform_identity(c.get('source_url','')):
                        task['source_url']=c['source_url']
                task['version'] += 1
                task['updated_at'] = now_iso()
                task['last_source_at'] = max(task['last_source_at'],message['captured_at'])
                self._save_task(db, task)
            else:
                task = dict(id=uuid.uuid4().hex,title=c['title'],course=c['course'],scope=c['scope'],kind=c['kind'],
                            deadline=c['deadline'],date_precision=c['date_precision'],checklist=[dict(text=x,done=False) for x in c['requirements']],
                            status='cancelled' if c['operation']=='cancel' else 'pending',version=1,created_at=now_iso(),updated_at=now_iso(),
                            last_source_at=message['captured_at'],sample=message['sample'],submission_method=c['submission_method'],teacher=c['teacher'],source_url=c['source_url'],
                            platform_status=c['platform_status'],confidence=c['confidence'],field_evidence=c['field_evidence'])
                self._save_task(db, task, task_key(c) or ('unmatched:' + task['id']))
            self._attach_proposal_sources(db,p,task)
            self._claim_identities(db,task,c,self._proposal_identities(db,p))
            if c.get('deadline') and task.get('deadline')==c['deadline']:
                basis=c.get('deadline_basis') if c.get('deadline_basis',{}).get('deadline')==c['deadline'] else None
                if basis:
                    db.execute('INSERT OR IGNORE INTO sources VALUES(?,?)',(task['id'],basis['message_id']))
                    db.execute('INSERT OR IGNORE INTO proposal_sources VALUES(?,?)',(p['id'],basis['message_id']))
                if not before or before.get('deadline')!=task['deadline']:
                    task['deadline_basis']=basis or dict(message_id=message['id'],deadline=c['deadline'],published_at=publication(message,db),evidence=c.get('deadline_evidence',''),kind=message.get('external',{}).get('kind','manual'))
            task['last_published_at']=task_publication(db,task,latest=True)
            from .relative_deadlines import record
            record(task,c,message,publication(message,db))
            if c.get('deadline'):
                task['deadline_reviewed_keys']=[r[0] for r in db.execute('SELECT m.capture_key FROM sources s JOIN messages m ON m.id=s.message_id WHERE s.task_id=? AND m.capture_key IS NOT NULL',(task['id'],))]
            self._save_task(db,task)
            p['source_message_ids']=self._proposal_source_ids(db,p['id']);p['source_count']=len(p['source_message_ids'])
            self._history(db, task, before, p['action'], message['id'])
            p['candidate'] = c
            db.execute("UPDATE proposals SET status='confirmed',task_id=?,data=? WHERE id=?", (task['id'],dump(p),p['id']))
            return task
    def _attach_proposal_sources(self,db,proposal,task):
        from .task_identity import platform_identity
        ids=set(self._proposal_source_ids(db,proposal['id']))|{proposal['message_id']}
        if not task.get('source_url') and len(proposal.get('identity_sources',{}))==1:
            task['source_url']=next(iter(proposal['identity_sources'].values()))['url'];self._save_task(db,task)
        for message_id in ids:
            db.execute('INSERT OR IGNORE INTO sources VALUES(?,?)',(task['id'],message_id))
            if not task.get('source_url'):
                row=db.execute('SELECT data FROM messages WHERE id=?',(message_id,)).fetchone()
                external=json.loads(row['data']).get('external',{}) if row else {}
                if external.get('kind')=='task_center' and platform_identity(external.get('url','')):
                    task['source_url']=external['url'];self._save_task(db,task)
    def _legacy_chat_duplicate(self, db, primary, duplicate):
        """Positive source proof for explicit repair, never automatic matching."""
        from .task_identity import normalized,canonical_title,possible_duplicate
        if duplicate.get('course') or self._task_platform_identities(db,duplicate):return False
        context=normalized(primary.get('course',''))
        if not context or normalized(primary.get('scope',''))!=context or normalized(duplicate.get('scope',''))!=context:return False
        if not possible_duplicate(duplicate,primary):return False
        expected=normalized(canonical_title(primary['title'],primary['course']))
        for row in db.execute('SELECT m.data FROM messages m JOIN sources s ON m.id=s.message_id WHERE s.task_id=?',(duplicate['id'],)):
            message=json.loads(row['data']);external=message.get('external',{})
            if (external.get('platform')=='chaoxing-web' and external.get('kind','chat')=='chat'
                    and normalized(message.get('scope',''))==context
                    and normalized(canonical_title(message['text'],primary['course']))==expected):return True
        return False
    def merge_duplicate_tasks(self, primary_id, duplicate_id, expected_versions, *, keep_primary_deadline=False):
        """Explicit, version-checked repair; retain the duplicate and old links."""
        from .task_identity import canonical_title,name_key,platform_identity
        if type(keep_primary_deadline) is not bool:raise ValidationError('合并截止选择无效。')
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            primary=self._task(db,primary_id);duplicate=self._task(db,duplicate_id)
            if primary['id']==duplicate['id']:return primary
            if any(expected_versions.get(task['id'])!=task['version'] for task in (primary,duplicate)):
                raise Conflict('任务版本已变化，请重新核对后合并。')
            identities=[self._task_platform_identity(db,task) for task in (primary,duplicate)]
            if (all(identities) and identities[0]!=identities[1]) or (not all(identities) and name_key(primary)!=name_key(duplicate) and not self._legacy_chat_duplicate(db,primary,duplicate)):
                raise Conflict('任务名称、课程、班级或平台编号不同，不能合并。')
            for key in ('status','kind','deadline','submission_method','teacher'):
                if primary.get(key) and duplicate.get(key) and primary[key]!=duplicate[key]:
                    raise Conflict('任务字段存在差异，不能直接合并：'+key)
            for task in (primary,duplicate):
                rows=db.execute('SELECT m.data FROM messages m JOIN sources s ON m.id=s.message_id WHERE s.task_id=?',(task['id'],))
                if not any(json.loads(row['data']).get('external',{}).get('platform')=='chaoxing-web' for row in rows):
                    raise Conflict('缺少学习通来源依据，不能直接合并。')
            task=dict(primary,title=canonical_title(primary['title'],primary['course']),version=primary['version']+1,updated_at=now_iso(),last_source_at=max(primary['last_source_at'],duplicate['last_source_at']))
            for key in ('deadline','submission_method','teacher','source_url','platform_status'):
                if key=='deadline' and keep_primary_deadline:continue
                if not task.get(key) and duplicate.get(key):task[key]=duplicate[key]
            if task.get('deadline'):task['date_precision']='date' if len(task['deadline'])==10 else 'minute'
            checklist={item['text']:dict(item) for item in primary['checklist']}
            for item in duplicate['checklist']:
                if item['text'] not in checklist:checklist[item['text']]=dict(item)
                else:checklist[item['text']]['done']|=item['done']
            task['checklist']=list(checklist.values())
            task['field_evidence']={**duplicate.get('field_evidence',{}),**primary.get('field_evidence',{})}
            retired=dict(duplicate,merged_into=primary['id'],merged_at=now_iso(),version=duplicate['version']+1)
            db.execute('UPDATE tasks SET task_key=?,data=?,version=? WHERE id=?',('merged:'+duplicate['id'],dump(retired),retired['version'],duplicate['id']))
            self._save_task(db,task)
            db.execute('UPDATE tasks SET task_key=? WHERE id=?',(task_key(dict(task,matchable=True)),task['id']))
            db.execute('INSERT OR IGNORE INTO sources SELECT ?,message_id FROM sources WHERE task_id=?',(task['id'],duplicate['id']))
            db.execute('UPDATE task_identities SET task_id=? WHERE task_id=?',(task['id'],duplicate['id']))
            self._claim_identities(db,task)
            history=[json.loads(row['data']) for row in db.execute('SELECT data FROM history WHERE task_id=? ORDER BY id',(duplicate['id'],))]
            record=dict(at=now_iso(),action='duplicate_task_merged',before=primary,after=task,message_id=None,merged_task=duplicate,merged_history=history)
            if keep_primary_deadline:record['keep_primary_deadline']=True
            db.execute('INSERT INTO history(task_id,data) VALUES(?,?)',(task['id'],dump(record)))
            return task
    def dismiss(self, proposal_id):
        with self.lock, self.connection() as db:
            row = db.execute('SELECT status FROM proposals WHERE id=?', (proposal_id,)).fetchone()
            if not row:
                raise NotFound('草稿不存在。')
            if row['status'] == 'confirmed':
                raise Conflict('已确认草稿不能忽略。')
            db.execute("UPDATE proposals SET status='dismissed' WHERE id=?", (proposal_id,))
            return dict(id=proposal_id,status='dismissed')
    def patch_task(self, task_id, changes):
        if not isinstance(changes, dict) or set(changes) - {'status','checklist','expected_version'}:
            raise ValidationError('任务只支持更新状态和材料勾选。')
        with self.lock, self.connection() as db:
            before = self._task(db, task_id)
            if changes.get('expected_version') is not None and changes['expected_version'] != before['version']:
                raise Conflict('任务已更新，请刷新后重试。')
            task = dict(before)
            if 'status' in changes:
                if changes['status'] not in STATUSES:
                    raise ValidationError('任务状态无效。')
                task['status'] = changes['status']
            if 'checklist' in changes:
                values = changes['checklist']
                if not isinstance(values, list) or len(values) != len(task['checklist']) or any(type(v) is not bool for v in values):
                    raise ValidationError('材料勾选应为与当前材料等长的布尔列表。')
                task['checklist'] = [dict(text=x['text'],done=v) for x,v in zip(task['checklist'],values)]
            task['updated_at'], task['version'] = now_iso(),task['version'] + 1
            self._save_task(db, task)
            self._history(db, task, before, 'status/checklist')
            return task
    def task_detail(self, task_id):
        with self.connection() as db:
            task = self._task(db, task_id)
            from .platform_check import read
            task['platform_check']=read(db,task)
            from .checkin_evidence import task_verification
            checkin_state=task_verification(db,task)
            if checkin_state:task['checkin_verification']=checkin_state
            task['sources'] = [json.loads(r['data']) for r in db.execute('SELECT m.data FROM messages m JOIN sources s ON m.id=s.message_id WHERE s.task_id=? ORDER BY m.rowid DESC', (task['id'],))]
            task['history'] = [json.loads(r['data']) for r in db.execute('SELECT data FROM history WHERE task_id=? ORDER BY id DESC', (task['id'],))]
            from .deadline_references import references
            task['deadline_references']=references(db,task)
            from .time_evidence import task_publication
            task['published_at']=task_publication(db,task)
            task['last_published_at']=task_publication(db,task,latest=True)
            return task
    def adopt_platform_status(self, task_id, changes):
        if not isinstance(changes,dict) or set(changes)!={'expected_version','observation_id'}:
            raise ValidationError('需要任务版本与当前核对记录。')
        from .platform_check import read
        with self.lock,self.connection() as db:
            before=self._task(db,task_id)
            observation=read(db,before)
            if before['version']!=changes['expected_version'] or not observation or observation['observation_id']!=changes['observation_id']:
                raise Conflict('任务或平台状态已变化，请刷新后重新核对。')
            if not observation['suggested_status'] or before['status']=='cancelled':
                raise ValidationError('此平台状态不能直接采用，请手动核对。')
            if (parse_timestamp(now_iso())-parse_timestamp(observation['checked_at'])).total_seconds()>86400:
                raise Conflict('核对记录超过 24 小时，请先同步学习通。')
            task=dict(before,status=observation['suggested_status'],version=before['version']+1,updated_at=now_iso(),status_basis=dict(platform=observation['status'],checked_at=observation['checked_at'],source_url=observation['source_url']))
            self._save_task(db,task)
            self._history(db,task,before,'platform_status_confirmed')
            return task
    def dashboard(self, at=None):
        moment = parse_timestamp(at or now_iso())
        tasks = self.tasks()
        active = [t for t in tasks if t['status'] not in ('submitted','cancelled') and t.get('checkin_verification') not in ('unverified','ambiguous','ended')]
        reminders = []
        for task in active:
            due = deadline_instant(task['deadline'])
            if not due:
                continue
            seconds = (due-moment).total_seconds()
            if seconds <= 86400:
                reminders.append(dict(task_id=task['id'],title=task['title'],course=task['course'],deadline=task['deadline'],status=task['status'],overdue=seconds <= 0,
                                      level='overdue' if seconds <= 0 else ('soon' if seconds <= 7200 else 'today')))
        upcoming = [t for t in active if t['deadline'] and 0 < (deadline_instant(t['deadline'])-moment).total_seconds() <= 7*86400]
        return dict(total=len(tasks),active=len(active),submitted=sum(t['status']=='submitted' for t in tasks),done=sum(t['status']=='done' for t in tasks),
                    overdue=sum(r['overdue'] for r in reminders),upcoming=len(upcoming),pending_reviews=len(self.proposals()),reminders=reminders,
                    courses=sorted({t['course'] for t in tasks if t['course']}),as_of=moment.isoformat())
    def calendar(self):
        def escape(x):
            return str(x).replace('\\','\\\\').replace('\n','\\n').replace(';','\\;').replace(',','\\,').replace('\r','')
        lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//CourseInbox//CN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:CourseInbox 课务日历']
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        for t in self.tasks():
            if not t['deadline'] or t['status'] == 'cancelled':
                continue
            lines += ['BEGIN:VEVENT', f"UID:{t['id']}@courseinbox.local",f'DTSTAMP:{stamp}',f"SEQUENCE:{t['version']}",f"SUMMARY:{escape(t['course']+' · '+t['title'])}",
                      'DESCRIPTION:' + escape('班级：' + t['scope'] + '\n状态：' + t['status'] + '\n任务要求：' + '、'.join(x['text'] for x in t['checklist']))]
            if t['date_precision'] == 'date':
                day = date.fromisoformat(t['deadline'])
                lines += [f'DTSTART;VALUE=DATE:{day.strftime("%Y%m%d")}',f'DTEND;VALUE=DATE:{(day+timedelta(days=1)).strftime("%Y%m%d")}']
            else:
                due = parse_timestamp(t['deadline']).astimezone(timezone.utc)
                lines += [f'DTSTART:{due.strftime("%Y%m%dT%H%M%SZ")}',f'DTEND:{(due+timedelta(minutes=15)).strftime("%Y%m%dT%H%M%SZ")}',
                          'BEGIN:VALARM','ACTION:DISPLAY','TRIGGER:-PT2H','DESCRIPTION:课程任务即将截止','END:VALARM']
            lines += ['END:VEVENT']
        lines += ['END:VCALENDAR']
        # RFC 5545 folding is measured in UTF-8 octets and must not split a code point.
        folded = []
        for line in lines:
            chunk = ''
            for char in line:
                if len((chunk+char).encode('utf-8')) > 75:
                    folded.append(chunk)
                    chunk = ' '
                chunk += char
            folded.append(chunk)
        return '\r\n'.join(folded) + '\r\n'
