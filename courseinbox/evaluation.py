"""Local, read-only notification evaluation. Reports never include source text."""
import hashlib
import ipaddress
import json
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from .agent import Agent, HttpProvider
from .core import ValidationError, normalize, now_iso, parse_message, validate_deadline


class EvaluationCancelled(RuntimeError):
    pass


ERROR_TYPES=('missing_source','processing_error','missed_task','extra_task','wrong_deadline','invented_deadline','wrong_operation','model_fallback','processing_limit')


def ollama_data(base_url, endpoint):
    import urllib.request
    local_provider(base_url, 'endpoint-check')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base_url.rstrip('/') + endpoint, timeout=4) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValidationError('本机模型列表过大。')
        return json.loads(raw)


def local_provider(base_url, model):
    url = urlsplit(base_url)
    try:
        loopback = url.hostname == 'localhost' or ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = False
    if url.scheme != 'http' or not loopback or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        raise ValidationError('评测仅支持本机 Ollama HTTP 地址，不发送到云端或其他电脑。')
    return HttpProvider('ollama', base_url, model)


def _messages(database):
    # No Inbox() on the source: opening an older database must not migrate it.
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        return [json.loads(row[0]) for row in db.execute('SELECT data FROM messages ORDER BY rowid')]


def _key(message):
    return hashlib.sha256(message['id'].encode()).hexdigest()[:24]


def _labels(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return validate_labels(value)


def validate_labels(value):
    if not isinstance(value,dict) or value.get('schema') not in (1, 2) or not isinstance(value.get('labels'), list):
        raise ValidationError('标注文件需要 schema=1 或 2 以及 labels 数组。')
    rows, seen, unreviewed = [], set(), 0
    for row in value['labels']:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or len(row['key']) not in (16, 24) or any(c not in '0123456789abcdef' for c in row['key']) or row['key'] in seen:
            raise ValidationError('标注键无效或重复。')
        seen.add(row['key'])
        if value['schema'] == 2 and row.get('reviewed') is not True:
            unreviewed += 1
            continue
        if value['schema'] == 1:
            if type(row.get('task')) is not bool:
                raise ValidationError('旧版标注 task 必须为布尔值。')
            tasks = [dict(title=None, deadline=row.get('deadline'), operation=row.get('operation'))] if row['task'] else []
        else:
            tasks = row.get('expected_tasks')
            if not isinstance(tasks, list) or len(tasks) > 20:
                raise ValidationError('每条通知需要至多20个已核对任务。')
        for task in tasks:
            if not isinstance(task, dict) or task.get('operation') not in ('create', 'update', 'cancel'):
                raise ValidationError('人工任务操作仅支持 create、update、cancel。')
            if value['schema'] == 2 and (not isinstance(task.get('title'), str) or not task['title'].strip()):
                raise ValidationError('已核对任务需要准确任务名称。')
            validate_deadline(task.get('deadline'))
            if any(field in task and not isinstance(task[field], str) for field in ('course', 'scope')):
                raise ValidationError('标注课程与班级必须为字符串。')
        rows.append(dict(key=row['key'], tasks=tasks))
    return rows, unreviewed


def prepare_labels(database, output, limit=200):
    if not 1 <= limit <= 200:
        raise ValidationError('每份标注工作文件选择1到200条消息。')
    # Stable hash order avoids selecting only the newest course or message kind.
    messages = sorted((m for m in _messages(database) if not m.get('sample')), key=_key)[:limit]
    value = dict(schema=2, prepared_at=now_iso(), origin='local_real_messages_unreviewed',
                 instructions='仅在本机核对原文。逐条填写 expected_tasks（title、deadline、operation，可选 course/scope），确认后设 reviewed=true；普通通知填空数组。review_text 等仅辅助核对，不作为答案。文件含原文，请勿公开提交。',
                 labels=[dict(key=_key(m), reviewed=False, expected_tasks=[], review_text=m['text'],
                              review_course=m.get('course', ''), review_scope=m.get('scope', ''),
                              review_published_at=m.get('captured_at'), source_kind=m.get('external', {}).get('kind', 'manual')) for m in messages])
    with Path(output).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    return dict(prepared=len(messages), reviewed=0)


def _rule_analysis(message):
    external = message.get('external', {})
    if external.get('time_known') is False:
        raise ValidationError('发布时间未知，不能用接收时间评估相对截止。')
    if external.get('kind') == 'course_notice':
        from .chaoxing import parse_notice_candidates
        return dict(candidates=parse_notice_candidates(external, message['captured_at'], message.get('course', ''), message.get('scope', '')))
    if external.get('kind') == 'task_center':
        from .chaoxing import normalize_web_message
        allowed = ('kind','message_id','title','url','task_type','deadline','published_at','submission_method','platform_status','teacher','field_evidence','description','attachments','detail_state','detail_error','media_pending_count')
        body = {key: external[key] for key in allowed if key in external}
        body.update(text=message['text'], course=message.get('course', ''), conversation=message.get('scope', ''), captured_at=message['captured_at'])
        return dict(candidates=normalize_web_message(body)['candidates'])
    return dict(candidates=parse_message(message['text'], message['captured_at'], message.get('course', ''), message.get('scope', '')))


def _ratio(value, total):
    return round(value / total, 4) if total else None


def evaluate(database, labels_path, *, mode='rules', model='', runner=None, limit=0, progress=None, cancel=None, split=None):
    if split not in (None,'development','holdout'):raise ValidationError('评测分组无效。')
    raw=json.loads(Path(labels_path).read_text(encoding='utf-8-sig'))
    validate_labels(raw)
    if split:
        if raw.get('schema')!=2 or any(row.get('split') not in ('development','holdout') for row in raw['labels']):
            raise ValidationError('此标注文件没有完整的开发集/留出集划分。')
        raw=dict(raw,labels=[row for row in raw['labels'] if row['split']==split])
    labels, unreviewed = validate_labels(raw)
    if limit:
        if limit < 0:
            raise ValidationError('评测条数不能小于0。')
        labels = labels[:limit]
    messages = _messages(database)
    index, ambiguous = {}, set()
    for message in messages:
        keys = [_key(message)]
        external = message.get('external', {})
        if external.get('kind') == 'course_notice' and isinstance(external.get('message_id'), str):
            keys.append(hashlib.sha256(external['message_id'].encode()).hexdigest()[:16])
        for key in keys:
            if key in index:
                ambiguous.add(key)
            index[key] = message
    counts = dict(tp=0, fp=0, fn=0)
    missing = errors = limited = fallbacks = deadline_total = deadline_right = update_total = update_right = operation_total = operation_right = 0
    unsupported_deadlines = sample_cases = legacy_cases = 0
    rows, elapsed = [], []
    run = runner or _rule_analysis
    for position,label in enumerate(labels,1):
        if cancel and cancel():raise EvaluationCancelled()
        key, expected = label['key'], label['tasks']
        deadline_total += sum(bool(task.get('deadline')) for task in expected)
        operation_total += len(expected)
        update_total += sum(task['operation']=='update' for task in expected)
        legacy_cases += any(task.get('title') is None for task in expected)
        if key not in index or key in ambiguous:
            missing += 1
            counts['fn'] += len(expected)
            rows.append(dict(key=key, status='missing' if key not in index else 'ambiguous',error_types=['missing_source']))
            if progress:progress(position,len(labels))
            continue
        sample_cases += bool(index[key].get('sample'))
        started = time.perf_counter()
        result, failed = {}, False
        try:
            result = run(index[key])
            candidates = result['candidates']
            if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
                raise ValidationError('候选格式无效。')
        except EvaluationCancelled:
            raise
        except Exception:
            candidates, failed = [], True
            errors += 1
        duration = round((time.perf_counter() - started) * 1000, 3)
        elapsed.append(duration)
        limited += bool(result.get('limited'))
        fallbacks += any(t.get('tool') == 'model_assist' and (t.get('result', {}).get('fallback') == 'rules' or t.get('status') == 'fallback') for t in result.get('trace', []))
        remaining, hits, case_dates, case_date_right, case_operations, case_unsupported = list(candidates), 0, 0, 0, 0, 0
        wrong_dates=wrong_operations=0
        for task in expected:
            # One-to-one identity matching; a correct date on another task cannot
            # make this task's deadline look correct.
            found = next((c for c in remaining if (task.get('title') is None or normalize(c.get('title', '')) == normalize(task['title'])) and all(field not in task or normalize(c.get(field, '')) == normalize(task[field]) for field in ('course', 'scope'))), None)
            if found is not None:
                remaining.remove(found)
                hits += 1
            if task.get('deadline'):
                wrong_dates += found is not None and found.get('deadline')!=task['deadline']
                deadline_right += found is not None and found.get('deadline') == task['deadline']
                case_dates += 1
                case_date_right += found is not None and found.get('deadline') == task['deadline']
            elif found is not None and found.get('deadline'):
                unsupported_deadlines += 1
                case_unsupported += 1
            operation_right += found is not None and found.get('operation') == task['operation']
            wrong_operations += found is not None and found.get('operation')!=task['operation']
            case_operations += found is not None and found.get('operation') == task['operation']
            if task['operation'] == 'update':
                update_right += found is not None and found.get('operation') == 'update'
        counts['tp'] += hits
        counts['fn'] += len(expected) - hits
        counts['fp'] += len(remaining)
        fallback=any(t.get('tool')=='model_assist' and t.get('result',{}).get('fallback')=='rules' for t in result.get('trace',[]))
        error_types=[name for name,present in (
            ('processing_error',failed),('missed_task',len(expected)>hits),('extra_task',bool(remaining)),
            ('wrong_deadline',wrong_dates),('invented_deadline',case_unsupported),('wrong_operation',wrong_operations),
            ('model_fallback',fallback),('processing_limit',result.get('limited'))) if present]
        delegated=next((t.get('result',{}).get('route') for t in result.get('trace',[]) if t.get('tool')=='analysis_route'),None)
        route=delegated if delegated in ('rules_verified','relative_extension') else 'model_assisted' if mode=='qwen' else 'rules'
        rows.append(dict(key=key, status='error' if failed else 'evaluated', expected=len(expected), predicted=len(candidates), matched=hits, elapsed_ms=duration,
                         deadline_cases=case_dates,deadline_right=case_date_right,operation_cases=len(expected),operation_right=case_operations,
                         unsupported_deadlines=case_unsupported,
                         error_types=error_types,route=route,fallback=fallback,limited=bool(result.get('limited'))))
        if progress:progress(position,len(labels))
    if cancel and cancel():raise EvaluationCancelled()
    times = sorted(elapsed)
    percentile = lambda fraction: times[max(0, math.ceil(len(times) * fraction) - 1)] if times else None
    complete = 100 <= len(labels) <= 200 and not (missing or errors or limited or fallbacks or sample_cases or legacy_cases or unsupported_deadlines) and bool(deadline_total and update_total)
    return dict(schema_version=2, generated_at=now_iso(), mode=mode, model=model, evaluation_split=split or 'all', labeled=len(labels), unreviewed=unreviewed,
                matched=len(labels)-missing, missing=missing, errors=errors, limited=limited, model_fallbacks=fallbacks,
                sample_cases=sample_cases,legacy_detection_only_cases=legacy_cases,unsupported_deadlines=unsupported_deadlines,
                routing={route:sum(r.get('route')==route for r in rows) for route in ('rules','rules_verified','model_assisted','relative_extension')},
                error_type_counts={name:sum(name in row.get('error_types',[]) for row in rows) for name in ERROR_TYPES},
                task_precision=_ratio(counts['tp'], counts['tp']+counts['fp']), task_recall=_ratio(counts['tp'], counts['tp']+counts['fn']),
                deadline_exact=_ratio(deadline_right, deadline_total), deadline_cases=deadline_total,
                update_recall=_ratio(update_right, update_total), update_cases=update_total,
                operation_exact=_ratio(operation_right, operation_total), counts=counts,
                latency_ms=dict(samples=len(times), mean=round(sum(times)/len(times),3) if times else None,p50=percentile(.5),p95=percentile(.95),maximum=times[-1] if times else None),
                target_evidence_complete=complete, cases=rows,
                scope='本机通知识别实验；缺失或错误不算正确。延迟包含规则/模型调用，不包含平台采集和Windows提醒。模型使用隔离空任务库，避免已确认答案泄漏；不证明用户体验、16GB整机资源或真实通知显示。')


def model_runner(inbox, provider):
    agent = Agent(inbox, provider)
    def run(message):
        # Preserve the source-specific rule extraction in both comparison arms.
        baseline = _rule_analysis(message)
        return agent.analyze(message['text'], message['captured_at'], message.get('course',''), message.get('scope',''), rule_candidates=baseline['candidates'])
    return run
