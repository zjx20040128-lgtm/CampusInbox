import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox
from courseinbox.chaoxing import ingest_web_message


class MessageTimingTests(unittest.TestCase):
    def setUp(self):
        clock=patch('courseinbox.core.now_iso',return_value='2026-10-17T18:00:00+08:00');clock.start();self.addCleanup(clock.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.job=dict(kind='task_center',message_id='timing_task',title='目标检测编程实践',text='目标检测编程实践；剩余319小时；未交',
            course='人工智能',conversation='一班',captured_at='2026-10-17T17:00:00+08:00',platform_status='未交',
            url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42')

    def receive(self,**changes):return ingest_web_message(self.box,{**self.job,**changes})

    def timing(self,message_id):return next(m for m in self.box.message_page(limit=200)['items'] if m['id']==message_id)['timing']

    def test_scan_time_is_not_publication_and_timer_is_not_deadline(self):
        result=self.receive();timing=self.timing(result['message']['id'])
        self.assertIsNone(timing['published_at']);self.assertIsNone(timing['deadline'])

    def test_deadline_range_filters_all_messages_before_pagination_in_china_time(self):
        self.receive(message_id='oct',deadline='2026-10-31T20:00:00+08:00')
        november=self.receive(message_id='nov',url=self.job['url'].replace('42','43'),deadline='2026-10-31T17:00:00Z')['message']
        self.receive(message_id='unknown',url=self.job['url'].replace('42','44'))
        page=self.box.message_page(limit=1,deadline_from='2026-11-01',deadline_to='2026-11-30')
        self.assertEqual(page['total'],1)
        self.assertEqual(page['unfiltered_total'],3)
        self.assertEqual(page['items'][0]['id'],november['id'])
        self.assertEqual(self.box.message_page(deadline_to='2026-10-31')['total'],1)

    def test_deadline_range_rejects_invalid_dates_and_reversed_bounds(self):
        from courseinbox.core import ValidationError
        for bounds in [dict(deadline_from='2026-02-30'),dict(deadline_to='11月'),dict(deadline_from='2026-12-01',deadline_to='2026-11-01')]:
            with self.assertRaises(ValidationError):self.box.message_page(**bounds)

    def test_explicit_publication_and_deadline_are_separate_from_scan_time(self):
        result=self.receive(published_at='2026-10-15T22:04:00+08:00',deadline='2026-10-30T23:59:00+08:00')
        timing=self.timing(result['message']['id'])
        self.assertEqual(timing['published_at'],'2026-10-15T22:04:00+08:00')
        self.assertEqual(timing['deadline'],'2026-10-30T23:59:00+08:00')
        self.assertEqual(result['message']['captured_at'],self.job['captured_at'])

    def test_known_publication_orders_before_unknown_without_receipt_sorting(self):
        scan=self.receive()['message']
        older=self.receive(message_id='older_task',url=self.job['url'].replace('workId=42','workId=43'),published_at='2026-10-15T12:00:00+08:00')['message']
        newer=self.box.ingest('普通消息',captured_at='2026-10-16T12:00:00+08:00')['message']
        self.assertEqual([m['id'] for m in self.box.message_page()['items']],[newer['id'],older['id'],scan['id']])

    def test_date_only_publication_keeps_its_precision_and_sorts_as_known(self):
        unknown=self.receive()['message']
        known=self.receive(message_id='date_only',url=self.job['url'].replace('workId=42','workId=43'),published_at='2026-10-15')['message']
        items=self.box.message_page()['items']
        self.assertEqual(items[0]['id'],known['id']);self.assertEqual(items[0]['timing']['published_at'],'2026-10-15')
        self.assertEqual(items[1]['id'],unknown['id'])

    def test_later_publication_evidence_enriches_without_another_message(self):
        original=self.receive()['message']
        replay=self.receive(message_id='new_transport',published_at='2026-10-15T22:04:00+08:00',field_evidence={'published_at':'发布时间：2026-10-15 22:04'})
        self.assertTrue(replay['duplicate']);self.assertEqual(self.box.message_page()['total'],1)
        self.assertEqual(self.timing(original['id'])['published_at'],'2026-10-15T22:04:00+08:00')
        self.assertEqual(self.box.message(original['id'])['text'],original['text'])

    def test_linked_release_notice_and_confirmed_deadline_supply_missing_fields(self):
        original=self.receive();self.box.confirm(original['proposals'][0]['id'])
        notice=ingest_web_message(self.box,dict(kind='course_notice',message_id='release_notice',title='作业:《人工智能》目标检测编程实践',
            text='课程名称：人工智能\n作业名称：目标检测编程实践\n结束时间：2026-10-30 23:59',course='人工智能',conversation='一班',sender='老师',
            captured_at='2026-10-15T22:06:00+08:00',url='https://notice.chaoxing.com/pc/notice/release_notice/detail',attachments=[]))
        self.box.confirm(notice['proposals'][0]['id'])
        with self.box.connection() as db:before=[tuple(row) for row in db.execute('SELECT * FROM messages ORDER BY rowid')]
        timing=self.timing(original['message']['id'])
        self.assertEqual(timing['published_at'],'2026-10-15T22:06:00+08:00');self.assertEqual(timing['publication_source'],'notice')
        self.assertEqual(timing['deadline'],'2026-10-30T23:59:00+08:00');self.assertEqual(timing['deadline_source'],'confirmed_task')
        with self.box.connection() as db:after=[tuple(row) for row in db.execute('SELECT * FROM messages ORDER BY rowid')]
        self.assertEqual(before,after)
        other=self.receive(message_id='other_class',url=self.job['url'].replace('classId=2','classId=3'))
        self.assertIsNone(self.timing(other['message']['id'])['deadline'])

    def test_dismissed_notice_keeps_source_deadline_without_restoring_draft(self):
        result=ingest_web_message(self.box,dict(kind='course_notice',message_id='dismissed_due',
            title='作业:《人工智能》实验',text='作业名称：实验\n开始时间：2026-10-23 23:35\n结束时间：2026-10-28 23:35',
            course='人工智能',conversation='一班',captured_at='2026-10-23T23:36:00+08:00',url='https://notice.chaoxing.com/pc/notice/dismissed_due/detail',attachments=[]))
        self.box.dismiss(result['proposals'][0]['id'])
        before=self.box.message(result['message']['id'])
        self.assertEqual(self.timing(before['id'])['deadline'],'2026-10-28T23:35:00+08:00')
        self.assertEqual(self.timing(before['id'])['deadline_source'],'message')
        self.assertEqual(self.box.message(before['id']),before)
        self.assertFalse(self.box.proposals())

    def test_dismissed_stale_start_date_is_not_reused_as_deadline(self):
        result=ingest_web_message(self.box,dict(kind='course_notice',message_id='stale_due',
            title='作业:《人工智能》实验',text='作业名称：实验\n开始时间：2026-10-23 23:35\n结束时间：2026-10-28 23:35',
            course='人工智能',conversation='一班',captured_at=None,url='https://notice.chaoxing.com/pc/notice/source_due/detail',attachments=[]))
        p=result['proposals'][0]
        with self.box.connection() as db:
            row=db.execute('SELECT data FROM proposals WHERE id=?',(p['id'],)).fetchone()
            old=json.loads(row['data']);old['candidate']['deadline']='2026-10-23T23:35:00+08:00'
            db.execute('UPDATE proposals SET data=? WHERE id=?',(json.dumps(old),p['id']))
        self.box.dismiss(p['id'])
        self.assertEqual(self.timing(result['message']['id'])['deadline'],'2026-10-28T23:35:00+08:00')

    def test_source_deadline_does_not_choose_one_of_multiple_tasks(self):
        from courseinbox.message_timing import source_deadline
        self.assertIsNone(source_deadline(dict(text='实验一截止2026-10-28 18:00；实验二截止2026-10-29 20:00'),None))

    def test_dismissed_unknown_publication_does_not_guess_relative_date(self):
        result=ingest_web_message(self.box,dict(kind='course_notice',message_id='relative_due',
            title='作业实验',text='作业实验明天18:00截止',course='人工智能',conversation='一班',captured_at=None,url='https://notice.chaoxing.com/pc/notice/source_due/detail',attachments=[]))
        for p in result['proposals']:self.box.dismiss(p['id'])
        self.assertIsNone(self.timing(result['message']['id'])['deadline'])


if __name__=='__main__':unittest.main()
