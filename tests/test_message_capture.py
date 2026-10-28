import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox
from courseinbox.chaoxing import ingest_web_message


class TaskCaptureTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch('courseinbox.core.now_iso',return_value='2026-10-17T18:05:00+08:00');self.clock.start();self.addCleanup(self.clock.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'inbox.sqlite3';self.box=Inbox(self.path)
        self.job=dict(kind='task_center',message_id='old_capture',title='目标检测编程实践',text='目标检测编程实践；剩余319小时22分钟；未交',
            course='人工智能',conversation='一班',captured_at='2026-10-17T17:00:00+08:00',platform_status='未交',
            url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42',
            field_evidence=dict(title='目标检测编程实践',deadline='剩余319小时22分钟'))

    def receive(self,**changes):return ingest_web_message(self.box,{**copy.deepcopy(self.job),**changes})

    def test_countdown_and_transport_id_change_do_not_create_new_message(self):
        first=self.receive();task=self.box.confirm(first['proposals'][0]['id'])
        replay=self.receive(message_id='new_capture',text='目标检测编程实践；剩余319小时20分钟；未交',captured_at='2026-10-17T17:02:00+08:00',field_evidence=dict(title=self.job['title'],deadline='剩余319小时20分钟'))
        self.assertTrue(replay['duplicate']);self.assertEqual(replay['message']['id'],first['message']['id'])
        self.assertEqual(self.box.message_page()['total'],1)
        updated=self.box.task_detail(task['id']);self.assertEqual(updated['version'],task['version'])
        self.assertEqual(updated['platform_check']['checked_at'],'2026-10-17T17:02:00+08:00')
        self.assertEqual(updated['sources'][0]['text'],self.job['text'])

    def test_real_deadline_description_and_status_changes_remain_separate(self):
        self.receive()
        for number,change in enumerate((dict(deadline='2026-10-30'),dict(description='请提交报告和源码'),dict(platform_status='已提交'))):
            result=self.receive(message_id='changed_'+str(number),**change)
            self.assertFalse(result['duplicate'])
        self.assertEqual(self.box.message_page()['total'],4)

    def test_different_classes_tasks_and_incomplete_ids_cannot_collapse(self):
        self.receive()
        for number,url in enumerate((self.job['url'].replace('classId=2','classId=3'),self.job['url'].replace('workId=42','workId=43'),self.job['url'].replace('&classId=2',''))):
            result=self.receive(message_id='different_'+str(number),url=url)
            self.assertFalse(result['duplicate'])
        self.assertEqual(self.box.message_page()['total'],4)

    def test_remaining_time_inside_an_instruction_is_material_content(self):
        self.receive(text='目标检测编程实践；请在剩余2小时内提交报告；未交')
        changed=self.receive(message_id='instruction_changed',text='目标检测编程实践；请在剩余3小时内提交报告；未交')
        self.assertFalse(changed['duplicate'],'only a standalone list countdown may be ignored')

    def test_clear_then_new_countdown_id_does_not_resurrect_message(self):
        first=self.receive();self.box.clear_messages([first['message']['id']])
        replay=self.receive(message_id='after_clear',text='目标检测编程实践；剩余300小时；未交')
        self.assertTrue(replay['duplicate']);self.assertTrue(replay['cleared'])
        self.assertEqual(self.box.message_page()['total'],0)

    def test_transport_id_reuse_cannot_replace_original_evidence(self):
        first=self.receive()
        replay=self.receive(description='伪造的新说明',platform_status='已提交',captured_at='2026-10-17T17:04:00+08:00')
        self.assertTrue(replay['duplicate']);self.assertEqual(replay['message']['external'],first['message']['external'])

    def test_legacy_duplicates_are_archived_without_losing_sources_or_history(self):
        first=self.receive();task=self.box.confirm(first['proposals'][0]['id'])
        before=self.box.task_detail(task['id']);second=copy.deepcopy(first['message'])
        second['id']='f'*32;second['external']['message_id']='legacy_countdown'
        second['text']='目标检测编程实践；剩余319小时20分钟；未交'
        second['external']['field_evidence']['deadline']='剩余319小时20分钟'
        second['captured_at']='2026-10-17T17:02:00+08:00'
        with self.box.connection() as db:
            db.execute('CREATE TABLE old_messages(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,data TEXT NOT NULL,sort_at TEXT NOT NULL,hidden_at TEXT)')
            db.execute('INSERT INTO old_messages SELECT id,fingerprint,data,sort_at,hidden_at FROM messages')
            db.execute('INSERT INTO old_messages VALUES(?,?,?,?,NULL)',(second['id'],hashlib.sha256(b'legacy_countdown').hexdigest(),json.dumps(second,ensure_ascii=False),self.box._message_time(second)))
            db.execute('DROP TABLE messages');db.execute('ALTER TABLE old_messages RENAME TO messages')
        with patch('courseinbox.message_capture.capture_key',side_effect=RuntimeError('interrupted migration')):
            with self.assertRaisesRegex(RuntimeError,'interrupted migration'):Inbox(self.path)
        with self.box.connection() as db:
            self.assertNotIn('capture_key',{row['name'] for row in db.execute('PRAGMA table_info(messages)')},'an interrupted migration must roll back its schema and data together')
        migrated=Inbox(self.path)
        self.assertEqual(migrated.message_page()['total'],1)
        self.assertEqual(len(migrated.messages(include_hidden=True)),2)
        self.assertEqual(migrated.message(first['message']['id'])['text'],first['message']['text'])
        self.assertEqual(migrated.message(second['id'])['text'],second['text'])
        after=migrated.task_detail(task['id']);self.assertEqual(after['sources'],before['sources']);self.assertEqual(after['history'],before['history'])
        self.assertEqual(Inbox(self.path).message_page()['total'],1,'restart must not resurrect folded duplicates')


if __name__=='__main__':unittest.main()
