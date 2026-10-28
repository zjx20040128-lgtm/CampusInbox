"""Reconcile only observed platform identities/content; never infer tasks by name."""
import json
import re
from datetime import datetime, timezone

from .chaoxing import normalize_web_message, task_detail_url, task_content_url
from .core import ValidationError, now_iso, parse_timestamp
from .message_capture import capture_key
from .task_identity import platform_identity


def section_key(course, group, kind):
    values = (course, group)
    if kind not in ('assignment', 'exam') or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', v) for v in values):
        return ''
    return '|'.join((*(str(int(v)) if v.isascii() and v.isdigit() else v for v in values), kind))


def status_neutral_key(message):
    external=message.get('external',{})
    status=external.get('platform_status','').strip()
    # Only standalone status labels are observation metadata; retain instructions.
    fragments=re.split(r'[；;\n]',message['text'])
    text='；'.join(part for part in fragments if not status or part.strip() not in (status,'状态：'+status,'状态:'+status))
    return capture_key(dict(external,platform_status=''),message['course'],message['scope'],text)


def detail_signature(message):
    external=message['external']
    files=[dict(name=a['name'],url=a['url']) for a in external.get('attachments',[])]
    return capture_key(dict(external,attachments=files),message['course'],message['scope'],external.get('task_body',message['text']))


class TaskInventory:
    def __init__(self, inbox, data=None):
        self.inbox = inbox
        self.data = data if isinstance(data, dict) and data.get('schema_version') == 1 else {}
        self.data.setdefault('schema_version', 1)
        self.data.setdefault('sections', {})
        self.data.setdefault('items', {})
        self.current_sections = set()

    def incomplete_repeat(self, job):
        try:
            value=normalize_web_message(job);external=value['external']
            old=self.data['items'].get(platform_identity(external.get('url')), {})
            return external.get('detail_state')!='read' and old.get('receipt_detail_read') is True and old.get('list_key')==capture_key(external,value['course'],value['scope'],value['text'])
        except (ValidationError,ValueError,TypeError,KeyError):return False

    def terminal_state(self, content_key):
        with self.inbox.connection() as db:
            if db.execute('SELECT 1 FROM cleared_messages WHERE fingerprint=?',(content_key,)).fetchone():return 'cleared'
            message=db.execute('SELECT id FROM messages WHERE capture_key=?',(content_key,)).fetchone()
            if not message:return None
            states={row[0] for row in db.execute('SELECT status FROM proposals WHERE message_id=? UNION SELECT p.status FROM proposal_sources s JOIN proposals p ON p.id=s.proposal_id WHERE s.message_id=?',(message['id'],message['id']))}
            if 'pending' in states or 'confirmed' in states:return None
            return 'archived' if 'archived' in states else 'ignored' if 'dismissed' in states else None

    def record(self, job, preliminary=False):
        try:
            value = normalize_web_message(job)
            external = value['external']
            key = platform_identity(external.get('url'))
            if external.get('kind') != 'task_center' or not key: return None
            section = key.rsplit('|', 1)[0]
            if section not in self.data['sections']: return None
            old = self.data['items'].get(key, {})
            content_key=capture_key(external,value['course'],value['scope'],value['text'])
            if preliminary and old.get('list_key')==content_key:
                return key
            incomplete_repeat=self.incomplete_repeat(job)
            signature=detail_signature(value)
            listed_only=bool(external.get('attachments')) and all(a.get('status')=='listed' for a in external['attachments'])
            preserve_media=listed_only and not external.get('media_pending_count') and old.get('detail_signature')==signature and old.get('receipt_media_complete') is True
            terminal_versions=dict(old.get('terminal_versions',{}))
            if old.get('neutral_key') and old.get('content_key')!=content_key:
                terminal=self.terminal_state(old['content_key'])
                if terminal:terminal_versions[old['neutral_key']]=terminal
            readable = external['task_type'] != 'exam' and bool(task_detail_url(external.get('detail_url') or external['url'],external['url']) or task_content_url(external['url']))
            detail = 'read' if external['detail_state'] == 'read' or incomplete_repeat else 'pending' if readable else 'manual'
            entry = dict(key=key, section=section, title=external['title'], course=value['course'],
                         kind=key.split('|')[2], content_key=old['content_key'] if incomplete_repeat or preserve_media else content_key,
                         list_key=content_key if preliminary else old.get('list_key',content_key),
                         receipt_detail_read=external['detail_state']=='read' or incomplete_repeat,
                         detail_signature=old.get('detail_signature',signature) if incomplete_repeat else signature,
                         receipt_media_complete=old.get('receipt_media_complete',False) if incomplete_repeat else preserve_media or not (any(a.get('status')!='extracted' for a in external.get('attachments',[])) or external.get('media_pending_count')),
                         neutral_key=old['neutral_key'] if incomplete_repeat or preserve_media else status_neutral_key(value),
                         terminal_versions=dict(list(terminal_versions.items())[-20:]),
                         checked_at=now_iso(), detail_state=detail,
                         detail_error=old.get('detail_error','') if incomplete_repeat else external.get('detail_error',''),
                         deadline=old.get('deadline') if incomplete_repeat else external.get('deadline'),
                         deadline_pending=old.get('deadline_pending',False) if incomplete_repeat else bool(detail=='read' and not external.get('deadline') and re.search(r'(?:至|截止|结束)[^\d]{0,8}\d{1,2}[-月/.]\d{1,2}',external.get('field_evidence',{}).get('deadline',''))),
                         media_pending=False if preserve_media else bool(any(a.get('status')!='extracted' for a in external.get('attachments',[])) or external.get('media_pending_count') or (incomplete_repeat and old.get('media_pending'))),
                         attempts=old.get('attempts', 0), retry_after=old.get('retry_after', 0), last_repair_at=old.get('last_repair_at'))
            self.data['items'][key] = entry
            return key
        except (ValidationError, ValueError, TypeError, KeyError):
            return None

    def receive(self, message):
        phase = message.get('phase')
        if phase == 'catalog':
            courses = message.get('courses')
            if not isinstance(courses, list) or len(courses) > 100: return
            sections = {}
            for course in courses:
                if not isinstance(course, dict): continue
                index = course.get('course_index')
                if type(index) is not int or not 1 <= index <= 100: continue
                for kind in ('assignment', 'exam'):
                    key = section_key(course.get('course_id'), course.get('class_id'), kind)
                    if not key: continue
                    old = self.data['sections'].get(key, {})
                    sections[key] = dict(old, key=key, course=str(course.get('course', ''))[:100], course_index=index, kind=kind,
                                         state=old.get('state', 'unchecked'), checked_at=old.get('checked_at'), unidentified_count=old.get('unidentified_count', 0))
            self.data['sections'] = sections
            self.data['items'] = {key: item for key, item in self.data['items'].items() if item['section'] in sections}
            self.current_sections.intersection_update(sections)
            self.data['catalog_at'] = now_iso()
            self.data['catalog_limited'] = message.get('truncated') is not False or len(sections) != len(courses) * 2
            return
        section = section_key(message.get('course_id'), message.get('class_id'), message.get('kind'))
        if section not in self.data['sections']: return
        value = self.data['sections'][section]
        if phase == 'failure':
            value.update(state='failed', reason=message.get('reason') if message.get('reason') in ('dom', 'timeout', 'http_5xx', 'http_error', 'expired') else 'unavailable')
            self.current_sections.discard(section)
            return
        if phase != 'section' or not isinstance(message.get('jobs'), list) or len(message['jobs']) > 100: return
        keys = set(); rejected = 0
        for job in message['jobs']:
            identity = platform_identity(job.get('url', '')) if isinstance(job, dict) else ''
            key = self.record(job,preliminary=message.get('preliminary',message.get('complete') is not True) is True) if identity.rsplit('|', 1)[0] == section else None
            if key: keys.add(key)
            else: rejected += 1
        complete = message.get('complete') is True and not rejected
        value.update(state='checked' if complete else 'partial', checked_at=now_iso(), unidentified_count=rejected, reason='identity' if rejected else '')
        if complete:
            self.data['items'] = {key: item for key, item in self.data['items'].items() if item['section'] != section or key in keys}
            self.current_sections.add(section)
        else: self.current_sections.discard(section)

    def snapshot(self):
        from .supplements import inventory_status
        with self.inbox.connection() as db:
            db.execute('BEGIN')
            supplements=inventory_status(db)
            rows=list(db.execute('SELECT id,capture_key,data FROM messages WHERE capture_key IS NOT NULL'))
            receipts = {row['capture_key']: row['id'] for row in rows}
            messages={row['id']:json.loads(row['data']) for row in rows}
            cleared = {row[0] for row in db.execute('SELECT fingerprint FROM cleared_messages')}
            # Attachment processing changes receipt hashes (listed -> skipped /
            # extracted). Match the same original content, not processing labels.
            detail_receipts={}
            for row in rows:
                message=messages[row['id']];external=message.get('external',{})
                identity=platform_identity(external.get('url',''))
                if identity and external.get('detail_state')=='read':
                    detail_receipts[(identity,detail_signature(message))]=(row['id'],row['capture_key'] in cleared)
            statuses = {}
            for row in db.execute('SELECT p.message_id,p.status FROM proposals p UNION SELECT s.message_id,p.status FROM proposal_sources s JOIN proposals p ON p.id=s.proposal_id'):
                statuses.setdefault(row['message_id'], set()).add(row['status'])
            linked = {row[0] for row in db.execute('SELECT DISTINCT message_id FROM sources')}
            settled=set()
            for row in db.execute('SELECT s.message_id,t.identity FROM sources s JOIN task_identities t ON t.task_id=s.task_id'):
                message=messages.get(row['message_id'])
                if not message:continue
                external=message.get('external',{})
                if platform_identity(external.get('url'))!=row['identity']:continue
                settled.add((row['identity'],status_neutral_key(message)))
            confirmed_times={}
            for row in db.execute('SELECT data FROM tasks'):
                task=json.loads(row['data'])
                if task.get('merged_into') or task.get('excluded_reason') or not task.get('deadline'):continue
                for identity in self.inbox._task_platform_identities(db,task):confirmed_times.setdefault(identity,[]).append(task)
        counts = dict.fromkeys(('missing', 'unrecognized', 'pending', 'confirmed', 'archived', 'ignored', 'cleared'), 0)
        items = []
        for entry in self.data['items'].values():
            message_id = receipts.get(entry['content_key'])
            receipt_cleared=False
            if not message_id and entry.get('receipt_detail_read'):
                message_id,receipt_cleared=detail_receipts.get((entry['key'],entry.get('detail_signature')),(None,False))
            states = statuses.get(message_id, set())
            state = ('cleared' if entry['content_key'] in cleared or receipt_cleared else 'missing' if not message_id else
                     'pending' if 'pending' in states else 'confirmed' if message_id in linked or 'confirmed' in states else
                     'archived' if 'archived' in states else 'ignored' if states else 'unrecognized')
            if state=='unrecognized':
                message=messages[message_id];external=message.get('external',{})
                signature=status_neutral_key(message)
                terminal=entry.get('terminal_versions',{}).get(signature)
                if terminal:state=terminal
                elif not external.get('extraction_warning') and (entry['key'],signature) in settled:state='confirmed'
                elif not external.get('extraction_warning') and external.get('detail_state')=='read':
                    from .platform_check import suggested_status
                    if suggested_status(external.get('platform_status',''))=='submitted':state='archived'
            counts[state] += 1
            effective=entry.get('deadline');pending=entry.get('deadline_pending',False);conflict=False;deadline_source='platform' if effective else 'unknown'
            accepted=confirmed_times.get(entry['key'],[])
            if len(accepted)==1:
                chosen=accepted[0]['deadline'];conflict=bool(effective and effective!=chosen)
                if not effective and pending and message_id:
                    evidence=messages[message_id].get('external',{}).get('field_evidence',{}).get('deadline','')
                    from .time_evidence import fragment_conflicts
                    conflict=fragment_conflicts(evidence,chosen)
                if entry['content_key'] in accepted[0].get('deadline_reviewed_keys',[]):conflict=False
                effective=chosen;pending=conflict;deadline_source='confirmed_task'
            detail_error=entry.get('detail_error','')
            if deadline_source=='confirmed_task' and not pending:detail_error=detail_error.replace('作答时间未包含完整年份，截止时间请核对原文。','')
            items.append({key: entry[key] for key in ('key', 'section', 'course', 'title', 'kind', 'checked_at', 'detail_state', 'media_pending', 'last_repair_at')} | dict(state=state, message_id=message_id,manual_supplement=supplements.get(message_id),detail_error=detail_error,raw_detail_error=entry.get('detail_error',''),deadline=effective,raw_deadline=entry.get('deadline'),deadline_source=deadline_source,deadline_pending=pending,deadline_conflict=conflict))
        sections = []
        moment = datetime.now(timezone.utc)
        for section in self.data['sections'].values():
            fresh = section['key'] in self.current_sections and section.get('checked_at') and (moment - parse_timestamp(section['checked_at'])).total_seconds() < 600
            sections.append(dict(section, freshness='fresh' if fresh else 'unverified'))
        sections.sort(key=lambda s: (s['course_index'], s['kind'] == 'exam'))
        indexes = {s['key']: i for i, s in enumerate(sections)}
        items.sort(key=lambda item: (indexes.get(item['section'], 999), item['key']))
        return dict(items=items, sections=sections, counts=counts, total=len(items), catalog_at=self.data.get('catalog_at'),
                    catalog_limited=self.data.get('catalog_limited', True), unchecked_sections=sum(s['state'] != 'checked' or s['freshness'] != 'fresh' for s in sections),
                    detail_pending=sum(item['detail_state'] == 'pending' for item in items), manual_details=sum(item['detail_state'] == 'manual' or item['media_pending'] for item in items),deadline_pending=sum(item['deadline_pending'] for item in items))

    def repair_keys(self, report, keys=None, automatic=False):
        if keys is not None and (not isinstance(keys, list) or not 1 <= len(keys) <= 50 or any(not isinstance(k, str) or k not in self.data['items'] for k in keys)):
            raise ValidationError('请选择清单中最多50个任务。')
        moment = datetime.now(timezone.utc).timestamp()
        result = []
        for item in sorted(report['items'], key=lambda item: item['state'] not in ('missing', 'unrecognized')):
            if keys is not None and item['key'] not in keys: continue
            if item['state'] in ('cleared', 'ignored', 'archived'): continue
            if item['state'] not in ('missing', 'unrecognized') and item['detail_state'] != 'pending': continue
            entry = self.data['items'][item['key']]
            if automatic and moment < entry.get('retry_after', 0): continue
            entry['attempts'] = min(10, entry['attempts'] + 1)
            entry['retry_after'] = moment + min(60, 10 * 2 ** min(entry['attempts'] - 1, 3))
            entry['last_repair_at'] = now_iso()
            result.append(item['key'])
            if len(result) >= (5 if automatic else 50): break
        return result
