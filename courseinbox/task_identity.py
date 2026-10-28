"""Conservative task names and stable Chaoxing IDs, without link signatures."""
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlsplit


def normalized(value):
    value=unicodedata.normalize('NFKC',value)
    return re.sub(r'[\W_]+', '', value, flags=re.UNICODE).lower()


def canonical_title(title, course):
    value=unicodedata.normalize('NFKC',title).strip()
    value = re.sub(r'^(?:作业|任务|考试|测验|实验)\s*[:：]\s*', '', value)
    match = re.match(r'^《([^》]+)》\s*(.+)$', value)
    if match and normalized(match[1]) == normalized(course):
        value = match[2].strip()
    return value or title.strip()


def identity_parts(url):
    parsed = urlsplit(url or '')
    if parsed.scheme != 'https' or parsed.netloc not in ('mooc1.chaoxing.com', 'mooc2-ans.chaoxing.com'):
        return dict(key='',problem='')
    values={};problem=''
    for key, value in parse_qsl(parsed.query):
        key = key.lower().replace('_', '').replace('-', '')
        if key not in ('courseid', 'classid', 'clazzid', 'workid', 'examid', 'id'):
            continue
        if key=='clazzid':key='classid'
        if value.isascii() and value.isdigit():value=str(int(value))
        if key in values and values[key] != value:
            problem='conflicting_ids'
        values[key] = value
    course, group = values.get('courseid'), values.get('classid')
    exam_route,work_route='/exam' in parsed.path.lower(),'/work/' in parsed.path.lower()
    for alias,route in (('examid',exam_route),('workid',work_route)):
        if route and values.get(alias) and values.get('id') and values[alias]!=values['id']:
            problem='conflicting_ids'
    exam = values.get('examid') or (values.get('id') if exam_route else None)
    work = values.get('workid') or (values.get('id') if work_route else None)
    if exam and work:problem='conflicting_ids'
    number = exam or work
    kind='exam' if exam or exam_route else 'assignment' if work or work_route else None
    if any(value and not re.fullmatch(r'[A-Za-z0-9_-]+',value) for value in (course,group,number)):problem='invalid_ids'
    key='|'.join((course,group,kind,number)) if not problem and all((course,group,number)) else ''
    return dict(key=key,problem=problem,course=course,group=group,kind=kind,number=number)


def platform_identity(url):
    return identity_parts(url)['key']


def compatible_parts(left,right):
    return not left.get('problem') and not right.get('problem') and all(
        not left.get(key) or not right.get(key) or left[key]==right[key]
        for key in ('course','group','kind','number'))


def name_key(task):
    return '|'.join((normalized(task['course']), normalized(task['scope']),
                     normalized(canonical_title(task['title'], task['course']))))


def review_title(title, context):
    """Normalize numbered aliases for review, without changing identity keys."""
    value=canonical_title(title,context)
    numeral=r'[0-9零〇一二两三四五六七八九十百千]+'
    digits={char:number for number,char in enumerate('零一二三四五六七八九')}
    digits.update({'〇':0,'两':2})
    def number(raw):
        if raw.isascii() and raw.isdigit():return str(int(raw))
        if all(char in digits for char in raw):return ''.join(str(digits[char]) for char in raw).lstrip('0') or '0'
        total=current=0
        for char in raw:
            if char in digits:current=digits[char]
            else:total+=(current or 1)*{'十':10,'百':100,'千':1000}[char];current=0
        return str(total+current)
    value=re.sub(r'第\s*('+numeral+r')\s*(?:次|个|项)?\s*(作业|实验|任务)',lambda m:m[2]+number(m[1]),value)
    value=re.sub(r'(作业|实验|任务)\s*('+numeral+r')',lambda m:m[1]+number(m[2]),value)
    return normalized(value)


def possible_duplicate(candidate,task):
    """Review only. Similarity must never select a task or modify its fields."""
    left=identity_parts(candidate.get('source_url',''));right=identity_parts(task.get('source_url',''))
    if left.get('key') and right.get('key'):return left['key']==right['key']
    for key in ('course','group','number','kind'):
        if left.get(key) and right.get(key) and left[key]!=right[key]:return False
    a,b=normalized(candidate.get('course','')),normalized(task.get('course',''))
    if a and b and a!=b:return False
    a_scope,b_scope=normalized(candidate.get('scope','')),normalized(task.get('scope',''))
    if a_scope and b_scope and a_scope!=b_scope and a_scope!=a and b_scope!=b:return False
    if (candidate.get('kind')=='exam')!=(task.get('kind')=='exam'):return False
    if left.get('number') and left.get('number')==right.get('number'):return True
    a=review_title(candidate['title'],candidate.get('course') or candidate.get('scope',''))
    b=review_title(task['title'],task.get('course') or task.get('scope',''))
    numbers=lambda value:[match[0] for match in re.finditer(r'\d+|第[一二三四五六七八九十百]+|(?:作业|实验|任务)[一二三四五六七八九十百]+',value)]
    heads=[re.match(r'^(作业|实验|任务)(\d+)',v) for v in (a,b)]
    if all(heads):
        if heads[0].groups()!=heads[1].groups():return False
    elif numbers(a) and numbers(b) and numbers(a)!=numbers(b):return False
    # Number-only rule titles lose the descriptive suffix of a chat card. Review
    # them only in the same explicit context; this never selects/merges a task.
    scope=normalized(candidate.get('scope',''))
    same_context=bool(scope and scope==normalized(task.get('scope','')) and
        (normalized(candidate.get('course','')) or scope)==(normalized(task.get('course','')) or scope))
    numbered=r'(?:作业|实验|任务)(?:\d+|[一二三四五六七八九十百]+)'
    if same_context and ((re.fullmatch(numbered,a) and b.startswith(a)) or (re.fullmatch(numbered,b) and a.startswith(b))):return True
    return bool(a and b and (a==b or (min(len(a),len(b))>=6 and (a in b or b in a or SequenceMatcher(None,a,b).ratio()>=0.86))))
