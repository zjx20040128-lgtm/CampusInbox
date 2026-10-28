import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox
from courseinbox.chaoxing import ingest_web_message

COURSE='软件工程高级管理技术'
TITLE='AI对进度管理的影响'


class DeadlineReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        clock=patch('courseinbox.core.now_iso',return_value='2026-10-24T11:40:00+08:00');clock.start();self.addCleanup(clock.stop)
        self.box=Inbox(Path(self.tmp.name)/'db.sqlite3')

    def notice(self,number='one',end='2026-10-28 23:35',course=COURSE):
        return ingest_web_message(self.box,dict(kind='course_notice',message_id='notice_'+number,title=f'作业:《{course}》{TITLE}',course=course,conversation=course,sender='学习通知',display_time='10-23 23:36',captured_at='2026-10-23T23:36:00+08:00',direction='received',url=f'https://notice.chaoxing.com/pc/notice/{number}/detail',attachments=[],text=f'课程名称：{course}\n作业名称：{TITLE}\n开始时间：2026-10-23 23:35\n结束时间：{end}'))

    def task_draft(self):
        return ingest_web_message(self.box,dict(kind='task_center',message_id='task_one',title=TITLE,text=TITLE+'；未交\n作答时间:10-23 23:35至10-28 23:35',course=COURSE,conversation=COURSE,captured_at='2026-10-24T10:54:00+08:00',task_type='assignment',deadline=None,platform_status='未交',url='https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=3',detail_state='read',field_evidence={'title':TITLE}))

    def test_ignored_notice_deadline_stays_visible_without_automatic_adoption(self):
        notice=self.notice();self.box.dismiss(notice['proposals'][0]['id'])
        draft=self.task_draft()['proposals'][0]
        listed=next(p for p in self.box.proposals() if p['id']==draft['id'])
        self.assertEqual(listed['deadline_references'][0]['deadline'],'2026-10-28T23:35:00+08:00')
        task=self.box.confirm(draft['id']);detail=self.box.task_detail(task['id'])
        self.assertIsNone(detail['deadline'])
        ref=detail['deadline_references'][0]
        self.assertEqual(ref['message_id'],notice['message']['id']);self.assertEqual(ref['status'],'dismissed')
        self.assertEqual(ref['evidence'],'2026-10-28 23:35')

    def test_different_courses_and_cleared_notices_do_not_leak_references(self):
        other=self.notice('other',course='另一门课程');self.box.dismiss(other['proposals'][0]['id'])
        own=self.notice();self.box.dismiss(own['proposals'][0]['id']);self.box.clear_messages([own['message']['id']])
        task=self.box.confirm(self.task_draft()['proposals'][0]['id'])
        self.assertEqual(self.box.task_detail(task['id']).get('deadline_references',[]),[])

    def test_conflicting_notice_dates_are_preserved_for_review(self):
        for number,end in [('one','2026-10-28 23:35'),('two','2026-10-29 23:35')]:
            n=self.notice(number,end);self.box.dismiss(n['proposals'][0]['id'])
        task=self.box.confirm(self.task_draft()['proposals'][0]['id'])
        detail=self.box.task_detail(task['id'])
        self.assertIsNone(detail['deadline'])
        self.assertEqual({r['deadline'] for r in detail['deadline_references']},{'2026-10-28T23:35:00+08:00','2026-10-29T23:35:00+08:00'})

    def test_inferred_year_is_not_presented_as_explicit_reference(self):
        notice=self.notice(end='10-28 23:35');self.box.dismiss(notice['proposals'][0]['id'])
        task=self.box.confirm(self.task_draft()['proposals'][0]['id'])
        self.assertEqual(self.box.task_detail(task['id'])['deadline_references'],[])


if __name__=='__main__':unittest.main()
