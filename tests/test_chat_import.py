import tempfile
import unittest
from pathlib import Path
from courseinbox.core import Inbox,ValidationError


class ChatImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')

    def receive(self,**changes):
        from courseinbox.chat_import import ingest
        body=dict(platform='wechat',conversation='软件工程课程群',sender='王老师',course='软件工程',published_at='2026-10-26T14:00:00+08:00',text='实验报告：明天20:00前提交PDF报告。')
        return ingest(self.box,{**body,**changes})

    def test_provenance_and_published_time_survive_without_task_confirmation(self):
        r=self.receive();m=r['message']
        self.assertEqual(m['chat_import']['sender'],'王老师')
        self.assertEqual(m['chat_import']['platform'],'wechat')
        self.assertEqual(m['scope'],'软件工程课程群')
        self.assertEqual(r['proposals'][0]['candidate']['deadline'],'2026-10-27T20:00:00+08:00')
        self.assertFalse(self.box.tasks())
        self.assertEqual(self.box.message_display(m['id'])['timing']['published_at'],'2026-10-26T14:00:00+08:00')

    def test_unknown_publication_never_uses_import_clock_even_on_reanalysis(self):
        r=self.receive(published_at=None)
        self.assertTrue(r['proposals'])
        self.assertTrue(all(p['candidate']['deadline'] is None for p in r['proposals']))
        self.assertIsNone(self.box.message_display(r['message']['id'])['timing']['published_at'])
        replay=self.box.reanalyze(r['message']['id'])
        self.assertTrue(all(p['candidate']['deadline'] is None for p in replay['proposals']))

    def test_unknown_publication_allows_explicit_full_date(self):
        r=self.receive(platform='qq',published_at=None,text='实验报告：请于2026年11月1日20:00前提交PDF。')
        self.assertEqual(r['proposals'][0]['candidate']['deadline'],'2026-11-01T20:00:00+08:00')

    def test_publication_date_in_text_is_not_a_deadline(self):
        r=self.receive(text='第一次作业：请完成报告，发布时间：2026年10月26日14:00。')
        self.assertTrue(all(not p['candidate']['deadline'] for p in r['proposals']))

    def test_replay_is_idempotent_but_sender_group_and_platform_are_distinct(self):
        first=self.receive();same=self.receive()
        self.assertTrue(same['duplicate']);self.assertEqual(first['message']['id'],same['message']['id'])
        for changes in [dict(platform='qq'),dict(conversation='另一课程群'),dict(sender='李老师'),dict(published_at='2026-10-27T14:00:00+08:00')]:
            self.assertFalse(self.receive(**changes)['duplicate'])

    def test_update_preserves_old_task_until_confirmation(self):
        first=self.receive(text='第一次实验报告：截止2026年11月1日20:00，提交PDF。')
        old=self.box.confirm(first['proposals'][0]['id'])
        changed=self.receive(platform='qq',published_at='2026-10-27T14:00:00+08:00',text='第一次实验报告延期至2026年11月3日20:00。')
        self.assertEqual(self.box.task_detail(old['id'])['deadline'],old['deadline'])
        updated=self.box.confirm(changed['proposals'][0]['id'])
        self.assertEqual(updated['id'],old['id']);self.assertEqual(updated['deadline'],'2026-11-03T20:00:00+08:00')

    def test_input_validation(self):
        for bad in [dict(platform='fake'),dict(platform={}),dict(conversation=''),dict(published_at='昨天'),dict(sender='x'*101),dict(unexpected=True)]:
            with self.assertRaises(ValidationError):self.receive(**bad)

    def test_vague_or_other_group_update_cannot_overwrite_a_task(self):
        from courseinbox.core import Conflict
        first=self.receive(text='实验报告：截止2026年11月1日20:00，提交PDF。')
        old=self.box.confirm(first['proposals'][0]['id'])
        changed=self.receive(platform='qq',published_at='2026-10-27T14:00:00+08:00',text='实验报告延期至2026年11月3日20:00。')
        with self.assertRaises(Conflict):self.box.confirm(changed['proposals'][0]['id'])
        self.assertEqual(self.box.task_detail(old['id'])['deadline'],old['deadline'])
