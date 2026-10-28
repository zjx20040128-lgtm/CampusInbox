"""Persistent notification handoff for the local Windows tray client."""
import hashlib
import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qsl,urlsplit

from .core import ValidationError, deadline_instant, dump, now_iso, parse_timestamp


class DesktopAlerts:
    def __init__(self,inbox):
        self.inbox=inbox
        with inbox.connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS desktop_alert_settings(key TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS desktop_alert_receipts(id TEXT PRIMARY KEY,acknowledged_at TEXT NOT NULL);
            ''')

    @staticmethod
    def _put(db,key,value):
        db.execute('INSERT OR REPLACE INTO desktop_alert_settings VALUES(?,?)',(key,dump(value)))

    @staticmethod
    def _get(db,key,default=None):
        row=db.execute('SELECT data FROM desktop_alert_settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _inventory_key(external):
        values={re.sub(r'[_-]','',key.lower()):value.strip() for key,value in parse_qsl(urlsplit(external.get('url','')).query)}
        course=values.get('courseid');group=values.get('classid') or values.get('clazzid')
        if not course or not group:return ''
        kind='exam' if external.get('task_type')=='exam' else 'assignment'
        return hashlib.sha256((course+'|'+group+'|'+kind).encode()).hexdigest()[:24]

    def _events(self,db,moment,initialized_at=None):
        events=[]
        initialized=self._get(db,'initialized_at') if initialized_at is None else initialized_at
        rows=db.execute("SELECT p.id,p.data,m.data AS message_data FROM proposals p JOIN messages m ON m.id=p.message_id WHERE p.status='pending' AND m.hidden_at IS NULL").fetchall()
        for row in rows:
            proposal=json.loads(row['data']);message=json.loads(row['message_data'])
            from .checkin_evidence import is_checkin,verification
            if not proposal.get('target_id') and is_checkin(message,db) and verification(db,message)!='verified':continue
            external=message.get('external') or {}
            learning=external.get('platform')=='chaoxing-web' or '学习通' in message.get('source','') or message.get('source')=='Android · com.chaoxing.mobile'
            if not learning or message.get('sample') or proposal.get('action') not in ('create','update','conflict'):continue
            published=message.get('received_at') if external.get('time_known') is False else message.get('captured_at')
            # Backfilled old publications remain reviewable, but are not new arrivals.
            if initialized and published and parse_timestamp(published)<parse_timestamp(initialized):continue
            candidate=proposal['candidate'];before=proposal.get('before') or {}
            changed=proposal.get('action')=='update' or bool(before and candidate.get('deadline') and candidate['deadline']!=before.get('deadline'))
            events.append(dict(id='proposal:'+row['id'],kind='deadline_change' if changed else 'new_pending',
                               title='学习通任务有变更，待核对' if changed else '学习通有新任务，待确认',
                               body=(candidate.get('course','')+' · '+candidate['title'])[:220],url='/?message='+message['id']+'#inbox',_source_kind=external.get('kind'),_source_at=message.get('captured_at'),_inventory_key=self._inventory_key(external)))
        for task in self.inbox.tasks():
            if task.get('checkin_verification') in ('unverified','ambiguous','ended'):continue
            if task.get('sample') or task['status'] in ('submitted','cancelled') or not task.get('deadline'):continue
            deadline=task['deadline'];level='';body=''
            if len(deadline)==10:
                day=date.fromisoformat(deadline);today=moment.date()
                if moment.hour<9:continue
                if today>day:level='overdue';body='截止日期已过，请核对提交情况。'
                elif today==day:level='day';body='今天为截止日期，具体时刻未明确，请核对原文。'
                elif today==day-timedelta(days=1):level='prior';body='明天为截止日期，具体时刻未明确，请核对原文。'
            else:
                seconds=(deadline_instant(deadline)-moment).total_seconds()
                if seconds<=0:level='overdue';body='任务已到截止时间，请核对提交情况。'
                elif seconds<=7200:level='soon';body='距离截止不超过 2 小时。'
                elif seconds<=86400:level='today';body='距离截止不超过 24 小时。'
                if level:body+=' 截止：'+parse_timestamp(deadline).strftime('%m-%d %H:%M')
            if not level:continue
            digest=hashlib.sha256(deadline.encode()).hexdigest()[:16]
            events.append(dict(id='deadline:'+task['id']+':'+digest+':'+level,
                               kind='deadline_overdue' if level=='overdue' else 'deadline_due',
                               title='课程任务已逾期' if level=='overdue' else '课程任务截止提醒',
                               body=(task.get('course','')+' · '+task['title']+'\n'+body)[:240],url='/?task='+task['id']+'#tasks'))
        priority={'deadline_change':0,'new_pending':1,'deadline_overdue':2,'deadline_due':3}
        return sorted(events,key=lambda event:(priority[event['kind']],event['id']))

    @staticmethod
    def _acknowledge(db,ids,at):
        db.executemany('INSERT OR IGNORE INTO desktop_alert_receipts VALUES(?,?)',((value,at) for value in ids))

    def poll(self,at=None,sync_status=None):
        moment=parse_timestamp(at or now_iso())
        with self.inbox.lock,self.inbox.connection() as db:
            events=self._events(db,moment)
            enabled=self._get(db,'enabled',True)
            if sync_status is not None:
                epoch=sync_status.get('inventory_epoch',0)
                if self._get(db,'inventory_epoch')!=epoch:
                    self._put(db,'inventory_epoch',epoch);self._put(db,'primed_sections',[])
                if sync_status.get('enabled'):
                    completed=set(sync_status.get('sources',{}).get('task_center',{}).get('discovered_sections',[]))
                    primed=set(self._get(db,'primed_sections',[]))
                    self._acknowledge(db,[event['id'] for event in events if event.get('_source_kind')=='task_center' and event.get('_inventory_key') not in primed],moment.isoformat())
                    self._put(db,'primed_sections',sorted(primed|completed))
            if not self._get(db,'initialized_at') or not enabled:
                self._acknowledge(db,[event['id'] for event in events],moment.isoformat())
                if not self._get(db,'initialized_at'):self._put(db,'initialized_at',moment.isoformat())
                return dict(enabled=enabled,events=[])
            received={row[0] for row in db.execute('SELECT id FROM desktop_alert_receipts')}
            return dict(enabled=enabled,events=[{key:value for key,value in event.items() if not key.startswith('_')} for event in events if event['id'] not in received][:20])

    def ack(self,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9:_.-]{1,200}',value) for value in ids):
            raise ValidationError('提醒确认标识无效。')
        with self.inbox.lock,self.inbox.connection() as db:
            self._acknowledge(db,ids,now_iso())
        return dict(ok=True)

    def settings(self,enabled,at=None):
        if type(enabled) is not bool:raise ValidationError('桌面提醒开关必须为布尔值。')
        moment=parse_timestamp(at or now_iso())
        with self.inbox.lock,self.inbox.connection() as db:
            previous=self._get(db,'enabled',True)
            if previous!=enabled or not self._get(db,'initialized_at'):
                self._acknowledge(db,[event['id'] for event in self._events(db,moment)],moment.isoformat())
            self._put(db,'enabled',enabled)
            if not self._get(db,'initialized_at'):self._put(db,'initialized_at',moment.isoformat())
        return dict(enabled=enabled)
