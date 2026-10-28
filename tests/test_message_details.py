import tempfile
import unittest
from pathlib import Path

from courseinbox.core import Inbox


class MessageDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.first=self.box.ingest('《软件工程》实验三，请提交报告，截止2026年11月20日18:00。',captured_at='2026-10-23T09:00:00+08:00')

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_draft_is_not_a_confirmed_task(self):
        detail=self.box.message_display(self.first['message']['id'])
        self.assertEqual(detail['related']['tasks'],[])
        self.assertEqual([p['id'] for p in detail['related']['proposals']],[self.first['proposals'][0]['id']])
        self.assertEqual(detail['related']['proposals'][0]['status'],'pending')

    def test_confirmed_task_is_linked_by_source_and_read_is_readonly(self):
        task=self.box.confirm(self.first['proposals'][0]['id'])
        self.box.ingest('《另一课程》第一次作业，请提交代码。')
        with self.box.connection() as db:before=list(db.iterdump())
        detail=self.box.message_display(self.first['message']['id'])
        self.assertEqual([t['id'] for t in detail['related']['tasks']],[task['id']])
        self.assertEqual(detail['related']['proposals'],[])
        self.assertEqual(detail['text'],self.first['message']['text'])
        with self.box.connection() as db:self.assertEqual(before,list(db.iterdump()))

    def test_supplement_draft_is_visible_from_both_evidence_records(self):
        task=self.box.confirm(self.first['proposals'][0]['id'])
        extra=self.box.supplement_message(self.first['message']['id'],{'target':'task:'+task['id'],'text':'请同时提交源代码。'})
        for message in (self.first['message'],extra['message']):
            detail=self.box.message_display(message['id'])
            self.assertEqual([p['id'] for p in detail['related']['proposals']],[extra['proposals'][0]['id']])

    def test_preserved_hidden_message_can_still_reach_its_task(self):
        task=self.box.confirm(self.first['proposals'][0]['id'])
        self.box.clear_messages([self.first['message']['id']])
        self.assertEqual(self.box.message_feed(),[])
        self.assertEqual(self.box.message_display(self.first['message']['id'])['related']['tasks'][0]['id'],task['id'])

    def test_ignored_draft_is_not_shown_as_pending(self):
        self.box.dismiss(self.first['proposals'][0]['id'])
        detail=self.box.message_display(self.first['message']['id'])
        self.assertEqual(detail['related']['proposals'][0]['status'],'dismissed')
        self.assertEqual(detail['related']['tasks'],[])

    def test_task_link_uses_source_even_for_a_nonprimary_message(self):
        task=self.box.confirm(self.first['proposals'][0]['id'])
        extra=self.box.supplement_message(self.first['message']['id'],{'target':'task:'+task['id'],'text':'请同时提交源代码。'})
        self.box.confirm(extra['proposals'][0]['id'])
        detail=self.box.message_display(extra['message']['id'])
        self.assertEqual([t['id'] for t in detail['related']['tasks']],[task['id']])
