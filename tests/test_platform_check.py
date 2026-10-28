import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox, Conflict
from courseinbox.chaoxing import ingest_web_message


class PlatformCheckTests(unittest.TestCase):
    def setUp(self):
        clock=patch('courseinbox.core.now_iso',return_value='2026-10-12T12:05:00+08:00')
        clock.start();self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox = Inbox(Path(self.tmp.name) / 'inbox.db')
        self.job = dict(kind='task_center', message_id='task_42_list', title='实验三', text='提交实验报告', description='提交实验报告',
                        course='数据库', conversation='一班', captured_at='2026-10-12T10:00:00+08:00',
                        url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42',
                        platform_status='未提交', deadline='2026-10-20T18:00:00+08:00')
        result = ingest_web_message(self.inbox, self.job)
        self.task = self.inbox.confirm(result['proposals'][0]['id'])

    def test_duplicate_refreshes_observation_without_new_proposal_or_task_version(self):
        result = ingest_web_message(self.inbox, dict(self.job, captured_at='2026-10-12T11:00:00+08:00'))
        self.assertTrue(result['duplicate'])
        task = self.inbox.task_detail(self.task['id'])
        self.assertEqual(task['platform_check']['checked_at'], '2026-10-12T11:00:00+08:00')
        self.assertEqual(task['version'], self.task['version'])
        self.assertEqual(len(self.inbox.proposals()), 0)

    def test_new_status_is_observation_until_explicitly_adopted(self):
        result = ingest_web_message(self.inbox, dict(self.job, message_id='task_42_submitted', platform_status='待批阅', captured_at='2026-10-12T11:00:00+08:00'))
        self.assertEqual(result['proposals'], [])
        task = self.inbox.task_detail(self.task['id'])
        self.assertEqual(task['status'], 'pending')
        check = task['platform_check']
        self.assertEqual(check['suggested_status'], 'submitted')
        adopted = self.inbox.adopt_platform_status(task['id'], dict(expected_version=task['version'], observation_id=check['observation_id']))
        self.assertEqual(adopted['status'], 'submitted')
        self.assertEqual(self.inbox.task_detail(task['id'])['history'][0]['action'], 'platform_status_confirmed')

    def test_delayed_scan_cannot_overwrite_or_confirm_newer_platform_state(self):
        ingest_web_message(self.inbox, dict(self.job, message_id='task_42_submitted', platform_status='已提交', captured_at='2026-10-12T11:00:00+08:00'))
        old = self.inbox.task_detail(self.task['id'])['platform_check']
        ingest_web_message(self.inbox, dict(self.job, message_id='task_42_returned', platform_status='已退回', captured_at='2026-10-12T12:00:00+08:00'))
        ingest_web_message(self.inbox, dict(self.job, captured_at='2026-10-12T10:30:00+08:00'))
        task = self.inbox.task_detail(self.task['id'])
        self.assertEqual(task['platform_check']['status'], '已退回')
        self.assertEqual(task['platform_check']['suggested_status'], 'pending')
        with self.assertRaises(Conflict):
            self.inbox.adopt_platform_status(task['id'], dict(expected_version=task['version'], observation_id=old['observation_id']))

    def test_other_class_and_unknown_status_do_not_confirm_submission(self):
        ingest_web_message(self.inbox, dict(self.job, message_id='task_other', conversation='二班', url=self.job['url'].replace('classId=2', 'classId=3'), platform_status='已提交'))
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['status'], '未提交')
        ingest_web_message(self.inbox, dict(self.job, message_id='task_ambiguous', platform_status='未提交 / 已提交', captured_at='2026-10-12T12:00:00+08:00'))
        self.assertIsNone(self.inbox.task_detail(self.task['id'])['platform_check']['suggested_status'])

    def test_detail_evidence_and_attachments_survive_validation(self):
        result = ingest_web_message(self.inbox, dict(self.job, message_id='task_detail', description='报告和源码',
            attachments=[dict(name='要求.docx', url='https://d0.cldisk.com/download/'+'a'*32, status='listed')],
            detail_state='read', detail_error=''))
        self.assertEqual(result['message']['external']['attachments'][0]['name'], '要求.docx')
        self.assertEqual(result['proposals'][0]['candidate']['requirements'], ['报告和源码', '附件：要求.docx'])

    def test_subsecond_replays_and_equal_time_conflict_cannot_restore_old_status(self):
        first=dict(self.job,message_id='task_a',platform_status='已提交',captured_at='2026-10-12T11:00:00.100+08:00')
        second=dict(first,message_id='task_b',platform_status='已退回',captured_at='2026-10-12T11:00:00.900+08:00')
        ingest_web_message(self.inbox,first);ingest_web_message(self.inbox,second);ingest_web_message(self.inbox,first)
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['status'],'已退回')
        ingest_web_message(self.inbox,dict(first,message_id='task_c',captured_at=second['captured_at']))
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['status'],'已退回')

    def test_future_or_missing_capture_time_cannot_refresh_observation(self):
        old=self.inbox.task_detail(self.task['id'])['platform_check']
        for value in ('2099-01-01T00:00:00+08:00',None):
            ingest_web_message(self.inbox,dict(self.job,message_id='future_'+str(value is None),captured_at=value,platform_status='已提交'))
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['observation_id'],old['observation_id'])

    def test_browser_milliseconds_are_not_rejected_by_second_precision_server_clock(self):
        ingest_web_message(self.inbox,dict(self.job,message_id='milliseconds',platform_status='已提交',captured_at='2026-10-12T12:05:00.500+08:00'))
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['status'],'已提交')

    def test_reading_diagnostic_change_does_not_freeze_status_freshness(self):
        ingest_web_message(self.inbox,dict(self.job,detail_state='skipped',detail_error='此入口尚未适配',captured_at='2026-10-12T11:00:00+08:00'))
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['checked_at'],'2026-10-12T11:00:00+08:00')

    def test_existing_task_source_before_upgrade_can_create_first_observation(self):
        with self.inbox.connection() as db:
            row=db.execute('SELECT id,data FROM messages').fetchone();message=json.loads(row['data'])
            for key in ('description','attachments','detail_state','detail_error'):message['external'].pop(key,None)
            db.execute('UPDATE messages SET data=? WHERE id=?',(json.dumps(message,ensure_ascii=False),row['id']))
            db.execute('DELETE FROM platform_observations')
        result=ingest_web_message(self.inbox,dict(self.job,captured_at='2026-10-12T11:00:00+08:00'))
        self.assertTrue(result['duplicate'])
        self.assertEqual(self.inbox.task_detail(self.task['id'])['platform_check']['status'],'未提交')
