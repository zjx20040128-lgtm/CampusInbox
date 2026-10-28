"""Read-only platform observations, separate from human-owned task progress."""
import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit


def identity(url, course, scope):
    if not url:
        return ''
    u = urlsplit(url)
    canonical = urlunsplit((u.scheme, u.netloc.lower(), u.path, urlencode(sorted(parse_qsl(u.query))), ''))
    return hashlib.sha256(json.dumps([canonical, course, scope], ensure_ascii=False).encode()).hexdigest()


def signature(external):
    fields = ['title', 'deadline', 'submission_method', 'description', 'attachments', 'task_type', 'teacher']
    return hashlib.sha256(json.dumps({k: external.get(k) for k in fields}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def suggested_status(status):
    value = ''.join(status.split())
    if value in ('已提交', '待批阅', '待批改', '已批阅', '已批改', '已完成'):
        # "已完成" is deliberately excluded: it can mean finished locally, not submitted.
        return 'submitted' if value != '已完成' else None
    if value in ('已退回', '退回重做', '待重交', '需重交', '未提交', '未交'):
        return 'pending'
    return None


def read(db, task):
    key = identity(task.get('source_url', ''), task['course'], task['scope'])
    row = db.execute('SELECT data FROM platform_observations WHERE identity=?', (key,)).fetchone()
    if not row:
        return None
    observation = json.loads(row['data'])
    observation.pop('signature', None)
    observation['suggested_status'] = suggested_status(observation['status'])
    return observation


def observe(db, external, course, scope, at, received_at):
    from .core import parse_timestamp, dump
    key = identity(external['url'], course, scope)
    row = db.execute('SELECT data FROM platform_observations WHERE identity=?', (key,)).fetchone()
    old = json.loads(row['data']) if row else None
    same_content = bool(old and old['signature'] == signature(external))
    # Queue replays cannot refresh freshness to arrival time or roll state backwards.
    # now_iso is second precision; retain the browser's subsecond ordering.
    if not external.get('time_known') or parse_timestamp(at) >= parse_timestamp(received_at)+timedelta(seconds=1):
        return same_content
    if old and parse_timestamp(at) <= parse_timestamp(old['checked_at']):
        return same_content
    observation = dict(status=external['platform_status'], checked_at=at, source_url=external['url'],
                       message_id=external['message_id'], signature=signature(external),
                       detail_state=external.get('detail_state', 'list_only'), detail_error=external.get('detail_error', ''))
    observation['observation_id'] = hashlib.sha256(dump([key, at, observation['status']]).encode()).hexdigest()
    db.execute('INSERT OR REPLACE INTO platform_observations VALUES(?,?)', (key, dump(observation)))
    return same_content
