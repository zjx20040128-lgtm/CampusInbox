import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox,Conflict
from courseinbox.chaoxing import ingest_web_message


class CheckinCreationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.clock=patch('courseinbox.core.now_iso',return_value='2026-10-26T16:30:00+08:00');self.clock.start();self.addCleanup(self.clock.stop)
        self.chat=ingest_web_message(self.box,dict(message_id='today-sign',text='位置签到',conversation='测试',captured_at='2026-10-26T16:26:00+08:00',direction='received'))

    def activity(self,**changes):
        job=dict(kind='checkin_activity',message_id='activity-today',text='位置签到',title='位置签到',conversation='测试',captured_at='2026-10-26T16:26:28+08:00',published_at='2026-10-26T16:26:28+08:00',deadline='2026-10-26T16:56:28+08:00',activity_id='123',course_id='456',class_id='789',field_evidence={'deadline':'学习通签到活动结束时间：2026-10-26 16:56:28'})
        return ingest_web_message(self.box,{**job,**changes})

    def test_detail_before_creation_is_retained_and_used_by_original_draft(self):
        result=self.activity()
        self.assertIsNotNone(result['message'])
        self.assertEqual(result['proposals'],[])
        proposal=next(p for p in self.box.proposals() if p['id']==self.chat['proposals'][0]['id'])
        self.assertEqual(proposal['candidate']['deadline'],'2026-10-26T16:56:28+08:00')
        task=self.box.confirm(proposal['id'])
        self.assertEqual(task['deadline'],'2026-10-26T16:56:28+08:00')
        self.assertEqual(len(self.box.task_detail(task['id'])['sources']),2)

    def test_missing_detail_blocks_creation_even_with_manual_deadline_or_kind(self):
        p=self.box.proposals()[0]
        self.assertTrue(p.get('checkin_unverified'))
        for edits in (None,{'deadline':'2027-01-01T00:00:00+08:00','kind':'homework'}):
            with self.assertRaises(Conflict):self.box.confirm(p['id'],edits)
        self.assertFalse(self.box.tasks())

    def test_platform_ended_without_deadline_is_retained_and_blocks_creation(self):
        result=self.activity(deadline=None,activity_state='ended',field_evidence={'activity_state':'已结束'})
        self.assertIsNotNone(result['message'])
        self.assertTrue(self.box.proposals()[0].get('checkin_expired'))
        self.assertIsNone(self.box.proposals()[0]['candidate']['deadline'])
        with self.assertRaises(Conflict):self.box.confirm(self.chat['proposals'][0]['id'])

    def test_unrelated_coursework_is_not_blocked(self):
        r=self.box.ingest('测试课程：提交实验报告，2027年1月1日截止。')
        self.assertTrue(self.box.confirm(r['proposals'][0]['id']))

    def test_legacy_unknown_signin_is_quarantined_without_changing_progress(self):
        with patch('courseinbox.checkin_evidence.verification',return_value='verified'):
            task=self.box.confirm(self.chat['proposals'][0]['id'])
        self.assertEqual(self.box.tasks()[0]['checkin_verification'],'unverified')
        self.assertEqual(self.box.dashboard()['active'],0)
        self.activity(deadline=None,activity_state='ended',field_evidence={'activity_state':'已结束'})
        detail=self.box.task_detail(task['id'])
        self.assertEqual(detail['checkin_verification'],'ended')
        self.assertEqual(detail['status'],'pending')
        self.assertEqual(detail['version'],task['version'])

    def test_same_title_other_session_still_cannot_unlock_creation(self):
        self.activity(message_id='old-activity',published_at='2026-10-25T16:26:28+08:00',deadline='2026-10-25T16:56:28+08:00')
        with self.assertRaises(Conflict):self.box.confirm(self.chat['proposals'][0]['id'])

    def test_ended_signal_overrides_future_deadline_without_inventing_an_end(self):
        self.activity(activity_state='ended',field_evidence={'activity_state':'已截止'})
        self.assertTrue(self.box.proposals()[0]['checkin_expired'])
        with self.assertRaises(Conflict):self.box.confirm(self.chat['proposals'][0]['id'])

    def test_unknown_and_ended_signins_do_not_emit_task_reminders(self):
        from courseinbox.desktop_alerts import DesktopAlerts
        from courseinbox.core import parse_timestamp
        alerts=DesktopAlerts(self.box)
        with self.box.connection() as db:
            self.assertEqual(alerts._events(db,parse_timestamp('2026-10-26T16:30:00+08:00')),[])
        with patch('courseinbox.checkin_evidence.verification',return_value='verified'):
            self.box.confirm(self.chat['proposals'][0]['id'],{'deadline':'2026-10-26T16:56:28+08:00'})
        self.activity(deadline=None,activity_state='ended',field_evidence={'activity_state':'已结束'})
        with self.box.connection() as db:
            self.assertEqual(alerts._events(db,parse_timestamp('2026-10-26T18:40:00+08:00')),[])

    def test_confirm_rechecks_expiry_and_does_not_allow_deadline_override(self):
        self.activity()
        with patch('courseinbox.core.now_iso',return_value='2026-10-26T18:40:00+08:00'):
            for edits in (None,{'deadline':None},{'deadline':'2027-01-01T00:00:00+08:00'}):
                with self.assertRaises(Conflict):self.box.confirm(self.chat['proposals'][0]['id'],edits)
        self.assertFalse(self.box.tasks())

    def test_other_session_does_not_supply_this_sessions_deadline(self):
        self.activity(message_id='old-activity',published_at='2026-10-25T16:26:28+08:00',deadline='2026-10-25T16:56:28+08:00')
        p=self.box.proposals()[0]
        self.assertIsNone(p['candidate']['deadline'])

    def test_two_activity_ids_cannot_be_treated_as_unique(self):
        self.activity()
        self.activity(message_id='ambiguous-activity',activity_id='999',deadline='2026-10-26T17:56:28+08:00')
        self.assertIsNone(self.box.proposals()[0]['candidate']['deadline'])
        with self.assertRaises(Conflict):self.box.confirm(self.chat['proposals'][0]['id'])

    def test_ended_other_activity_without_date_cannot_bypass_ambiguity_guard(self):
        self.activity()
        self.activity(message_id='second-ended',activity_id='999',deadline=None,activity_state='ended',field_evidence={'activity_state':'已结束'})
        self.assertTrue(self.box.proposals()[0]['checkin_ambiguous'])
        with self.assertRaises(Conflict):self.box.confirm(self.chat['proposals'][0]['id'])

    def test_renaming_at_creation_does_not_remove_expiry_and_reminder_protection(self):
        self.activity()
        task=self.box.confirm(self.chat['proposals'][0]['id'],{'title':'今天课堂签到'})
        with patch('courseinbox.core.now_iso',return_value='2026-10-26T18:40:00+08:00'):
            self.assertEqual(self.box.task_detail(task['id']).get('checkin_verification'),'ended')
            self.assertEqual(self.box.dashboard()['active'],0)

    def test_supplement_does_not_bypass_original_signin_verification(self):
        r=self.box.supplement_message(self.chat['message']['id'],dict(text='截止时间：2027年1月1日18:00',target='proposal:'+self.chat['proposals'][0]['id']))
        with self.assertRaises(Conflict):self.box.confirm(r['proposals'][0]['id'])

    def test_custom_title_card_also_requires_verified_activity(self):
        r=ingest_web_message(self.box,dict(message_id='custom',text='周二课堂签到',activity_type='checkin',conversation='其他课程',captured_at='2026-10-26T16:26:00+08:00',direction='received'))
        self.assertEqual(r['proposals'][0]['candidate']['title'],'周二课堂签到')
        with self.assertRaises(Conflict):self.box.confirm(r['proposals'][0]['id'])
        self.activity(message_id='custom-detail',text='周二课堂签到',title='周二课堂签到',conversation='其他课程',activity_id='custom-1')
        refreshed=self.box.reanalyze(r['message']['id'])['proposals'][0]
        self.assertEqual(refreshed['candidate']['title'],'周二课堂签到')
        task=self.box.confirm(refreshed['id'])
        self.assertEqual(task['deadline'],'2026-10-26T16:56:28+08:00')
        self.assertEqual(self.box.task_detail(task['id'])['checkin_verification'],'verified')

    def test_non_card_coursework_about_signin_program_is_not_quarantined(self):
        r=ingest_web_message(self.box,dict(message_id='program',text='软件工程：提交签到程序作业，2027年1月1日截止',conversation='测试',captured_at='2026-10-26T16:26:00+08:00',direction='received'))
        task=self.box.confirm(r['proposals'][0]['id'])
        self.assertFalse(self.box.task_detail(task['id']).get('checkin_verification'))

    def test_legacy_custom_title_without_card_metadata_is_not_an_escape(self):
        r=ingest_web_message(self.box,dict(message_id='legacy-custom',text='周二课堂签到',conversation='其他课程',captured_at='2026-10-26T16:26:00+08:00',direction='received'))
        with self.assertRaises(Conflict):self.box.confirm(r['proposals'][0]['id'])
