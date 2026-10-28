import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.chaoxing import ingest_web_message
from courseinbox.core import Inbox, Conflict


AT='2026-10-20T21:16:00+08:00'
BODY='课程名称：测试\n作业名称：作业20261015\n你的作业还有24个小时就要结束，请尽快作答'


class ReminderNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'inbox.sqlite3';self.box=Inbox(self.path)
        clock=patch('courseinbox.core.now_iso',return_value='2026-10-20T21:27:59+08:00');clock.start();self.addCleanup(clock.stop)

    def notice(self,title='作业结束提醒',body=BODY,number='1'):
        return ingest_web_message(self.box,dict(kind='course_notice',message_id='reminder-'+number,title=title,text=body,
            sender='学习通知',captured_at=AT,display_time='10-20 21:16',direction='received',
            url='https://notice.chaoxing.com/pc/notice/$CACG$reminder-'+number+'/detail',attachments=[]))

    def legacy(self):
        with patch('courseinbox.intake_policy.is_reminder_notice',return_value=False,create=True):
            result=self.notice();task=self.box.confirm(result['proposals'][0]['id'])
        return result,task

    def test_countdown_notice_is_archived_without_claiming_the_assignment_has_ended(self):
        result=self.notice();proposal=result['proposals'][0]
        self.assertEqual(proposal['status'],'archived')
        self.assertEqual(proposal['archive_reason'],'reminder_only')
        self.assertEqual(self.box.proposals(),[]);self.assertEqual(self.box.tasks(),[])
        self.assertIn(BODY,self.box.message(result['message']['id'])['text'])
        with self.assertRaises(Conflict):self.box.confirm(proposal['id'])

    def test_task_and_exam_template_variants_are_not_new_work(self):
        for number,kind in enumerate(('任务','考试','测验')):
            with self.subTest(kind=kind):
                result=self.notice(kind+'截止提醒',f'课程名称：测试\n{kind}名称：第一项\n你的{kind}还有2个小时就要结束，请尽快作答',str(number+2))
                self.assertEqual(result['proposals'][0]['archive_reason'],'reminder_only')

    def test_reextracting_a_reminder_does_not_restore_a_create_draft(self):
        result=self.notice();self.box.reanalyze(result['message']['id'])
        self.assertEqual(self.box.proposals(),[])
        self.assertTrue(all(p['archive_reason']=='reminder_only' for p in self.box.proposals('archived')))

    def test_existing_real_task_is_not_changed_by_countdown_notice(self):
        item=self.box.ingest('《测试》作业名称：作业20261015\n请提交报告。',captured_at=AT)
        task=self.box.confirm(item['proposals'][0]['id']);self.notice()
        self.assertEqual(self.box.tasks()[0]['id'],task['id']);self.assertEqual(self.box.tasks()[0]['version'],task['version'])
        self.assertEqual(self.box.tasks()[0]['status'],'pending');self.assertEqual(len(self.box.tasks()),1)

    def test_real_instructions_and_explicit_deadline_changes_still_need_review(self):
        for number,title,body in (('10','第二次作业','请在作业结束前提交报告。'),
            ('11','作业截止提醒','课程名称：测试\n作业名称：第二次作业\n请阅读附件并提交报告。'),
            ('12','作业结束提醒',BODY+'\n截止时间现延期到2026年10月30日。'),
            ('13','作业结束提醒',BODY+'\n新增要求：请阅读附件并提交报告。')):
            with self.subTest(title=title):self.assertEqual(self.notice(title,body,number)['proposals'][0]['status'],'pending')

    def test_old_pending_reminder_is_reconciled_and_stale_confirmation_is_blocked(self):
        with patch('courseinbox.intake_policy.is_reminder_notice',return_value=False,create=True):result=self.notice()
        with self.assertRaises(Conflict):self.box.confirm(result['proposals'][0]['id'])
        reopened=Inbox(self.path)
        self.assertEqual(reopened.proposals(),[]);self.assertEqual(reopened.proposals('archived')[0]['archive_reason'],'reminder_only')

    def test_explicit_repair_preserves_record_sources_and_audit_but_removes_false_task(self):
        result,task=self.legacy();fixed=self.box.exclude_reminder_task(task['id'],task['version'])
        self.assertEqual(fixed['excluded_reason'],'reminder_only');self.assertEqual(self.box.tasks(),[])
        detail=self.box.task_detail(task['id'])
        self.assertEqual(detail['sources'][0]['id'],result['message']['id'])
        self.assertEqual(detail['history'][0]['action'],'reminder_misclassification_corrected')
        self.assertEqual(self.box.proposals('archived')[0]['archive_reason'],'reminder_only')
        self.assertEqual(Inbox(self.path).tasks(),[])

    def test_repair_refuses_stale_version_and_real_work(self):
        _,task=self.legacy()
        with self.assertRaises(Conflict):self.box.exclude_reminder_task(task['id'],task['version']+1)
        item=self.box.ingest('《数学》第一次作业，请提交报告。',captured_at=AT)
        real=self.box.confirm(item['proposals'][0]['id'])
        with self.assertRaises(Conflict):self.box.exclude_reminder_task(real['id'],real['version'])


if __name__=='__main__':unittest.main()
