import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox, ValidationError


class DesktopInboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.box = Inbox(Path(self.tmp.name) / 'inbox.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def message(self, text, published, received='2026-10-16T12:00:00+08:00', external=None):
        with patch('courseinbox.core.now_iso', return_value=received):
            return self.box.ingest(text, captured_at=published, external=external)

    def test_source_time_orders_before_arrival_and_pagination(self):
        latest = self.message('最近通知', '2026-10-16T09:00:00+08:00')['message']
        old = self.message('补读旧通知', '2025-03-09T09:00:00+08:00')['message']
        self.assertEqual(self.box.messages()[0]['id'], latest['id'])
        page = self.box.message_page(limit=1)
        self.assertEqual(page['items'][0]['id'], latest['id'])
        self.assertEqual(page['total'], 2)
        self.assertEqual(self.box.message_page(limit=1, offset=1)['items'][0]['id'], old['id'])

    def test_unknown_publication_uses_receipt_time(self):
        ext = dict(platform='chaoxing-web', message_id='unknown-time', kind='chat', time_known=False)
        unknown = self.message('未知时间的通知', '2020-01-01T00:00:00+08:00', external=ext)['message']
        self.message('已知发布时间', '2026-10-15T12:00:00+08:00')
        self.assertEqual(self.box.messages()[0]['id'], unknown['id'])

    def test_cleanup_snapshot_keeps_concurrent_message_and_replay_stays_cleared(self):
        old = self.message('普通消息，节日快乐', '2026-10-15T09:00:00+08:00')
        snapshot = self.box.cleanup_preview()
        fresh = self.message('确认期间收到的新消息', '2026-10-16T09:00:00+08:00')
        result = self.box.clear_messages(snapshot['ids'])
        self.assertEqual(result['cleared'], 1)
        self.assertEqual([m['id'] for m in self.box.messages()], [fresh['message']['id']])
        replay = self.message('普通消息，节日快乐', '2026-10-15T09:00:00+08:00')
        self.assertTrue(replay['duplicate'])
        self.assertTrue(replay['cleared'])
        self.assertEqual(self.box.message_page()['total'], 1)
        self.assertNotIn(old['message']['id'], [m['id'] for m in self.box.messages()])

    def test_cleanup_preserves_confirmed_task_and_original_evidence(self):
        result = self.message('《数学》第一次作业，请于2026年10月30日18:00前提交报告。', '2026-10-15T09:00:00+08:00')
        task = self.box.confirm(result['proposals'][0]['id'])
        cleared = self.box.clear_messages([result['message']['id']])
        self.assertEqual(cleared['preserved'], 1)
        self.assertEqual(self.box.messages(), [])
        detail = self.box.task_detail(task['id'])
        self.assertEqual(detail['sources'][0]['text'], result['message']['text'])
        self.assertEqual(len(self.box.tasks()), 1)
        self.assertEqual(len(self.box.messages(include_hidden=True)), 1)

    def test_cleanup_preserves_pending_draft_and_unknown_deadline_task(self):
        result = self.message('《数学》第二次作业，请完成实验报告。', '2026-10-15T09:00:00+08:00')
        self.box.clear_messages([result['message']['id']])
        self.assertEqual(len(self.box.proposals()), 1)
        task = self.box.confirm(result['proposals'][0]['id'])
        self.assertIsNone(task['deadline'])
        self.assertEqual(self.box.tasks()[0]['id'], task['id'])

    def test_cleanup_validates_entire_request_before_mutation(self):
        item = self.message('保留普通通知', '2026-10-15T09:00:00+08:00')['message']
        with self.assertRaises(ValidationError):
            self.box.clear_messages([item['id'], '../invalid'])
        self.assertEqual(len(self.box.messages()), 1)

    def test_restoring_archive_replaces_old_archive_entry_and_retains_audit(self):
        external=dict(platform='chaoxing-web',message_id='restore-old',kind='chat',time_known=True)
        item=self.message('《数学》第一次作业，截止2025年3月9日17:00，请提交报告。','2025-03-08T09:00:00+08:00',external=external)
        self.assertEqual(len(self.box.proposals('archived')),1)
        self.box.reanalyze(item['message']['id'])
        self.assertEqual(len(self.box.proposals()),1)
        self.assertEqual(self.box.proposals('archived'),[])
        self.assertEqual(len(self.box.proposals(None)),2)

    def test_hidden_sources_still_receive_attachment_improvements(self):
        from courseinbox.chaoxing import ingest_web_message
        for confirmed in (False,True):
            with self.subTest(confirmed=confirmed):
                payload=dict(message_id='hidden-retry-'+str(confirmed),kind='course_notice',title='《数学》第一次作业'+str(confirmed),text='请于2026年10月30日前提交报告，具体要求见附件。',course='数学',sender='老师',captured_at='2026-10-15T09:00:00+08:00',url='https://notice.chaoxing.com/pc/notice/hidden-retry/detail',attachments=[dict(name='说明.txt',url='',status='failed',text='')])
                result=ingest_web_message(self.box,payload)
                task=self.box.confirm(result['proposals'][0]['id']) if confirmed else None
                self.box.clear_messages([result['message']['id']])
                payload['attachments'][0].update(status='extracted',text='请提交报告和源代码。')
                updated=ingest_web_message(self.box,payload)
                stored=self.box.message(result['message']['id'])
                self.assertEqual(stored['external']['attachments'][0]['status'],'extracted')
                self.assertEqual(updated['message']['external'],stored['external'])
                self.assertNotIn(stored['id'],[message['id'] for message in self.box.messages()])
                if task:self.assertEqual(self.box.task_detail(task['id'])['version'],task['version'])

    def test_cleared_fingerprints_survive_more_than_ten_thousand_later_clears(self):
        old=self.message('不应重新出现的旧消息','2025-03-09T09:00:00+08:00')
        self.box.clear_messages([old['message']['id']])
        with self.box.connection() as db:
            db.executemany('INSERT INTO cleared_messages VALUES(?,?,?)',((f'legacy-{n}',f'{n:032x}','2026-10-16T12:00:00+08:00') for n in range(10000)))
        newest=self.message('另一个清理记录','2026-10-16T09:00:00+08:00')
        self.box.clear_messages([newest['message']['id']])
        replay=self.message('不应重新出现的旧消息','2025-03-09T09:00:00+08:00')
        self.assertTrue(replay['duplicate'])
        self.assertTrue(replay['cleared'])
        self.assertEqual(self.box.messages(),[])

    def test_ordering_backfills_existing_schema_without_losing_messages(self):
        import sqlite3
        path = Path(self.tmp.name) / 'legacy.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE messages(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, data TEXT NOT NULL)')
        db.close()
        legacy = Inbox(path)
        legacy.ingest('迁移后正常保存', captured_at='2026-10-15T09:00:00+08:00')
        self.assertEqual(len(Inbox(path).messages()), 1)
        self.assertEqual(len(list((path.parent/'backups').glob('legacy-before-desktop-reliability-*.sqlite3'))),1)


if __name__ == '__main__':
    unittest.main()
