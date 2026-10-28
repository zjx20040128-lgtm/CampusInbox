import json
import tempfile
import unittest
from pathlib import Path
from courseinbox.core import Inbox,parse_message,parse_timestamp,extract_deadline,dump
from courseinbox.core import Conflict
from courseinbox.chaoxing import ingest_web_message

AT='2026-10-12T10:45:00+08:00'
START='2026-10-12T10:41:00+08:00'


class DeadlineRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')

    def notice(self):
        return ingest_web_message(self.box,dict(kind='course_notice',message_id='start_only',title='作业:《数字图像处理》作业1：BMP文件的读写',text='课程名称：数字图像处理\n作业名称：作业1：BMP文件的读写\n开始时间：2026-10-12 10:41',course='数字图像处理',conversation='数字图像处理',captured_at=AT,url='https://notice.chaoxing.com/pc/notice/start_only/detail',attachments=[]))

    def stale(self):
        n=self.notice();p=n['proposals'][0]
        p['candidate'].update(deadline=START,date_precision='minute',deadline_evidence='2026-10-12 10:41')
        with self.box.connection() as db:db.execute('update proposals set data=? where id=?',(dump(p),p['id']))
        return n,p

    def test_start_publication_receipt_labels_never_become_deadline(self):
        for label in ['开始时间','开始日期','作答开始时间','发布时间','发布日期','发布于','通知时间','接收时间','采集时间']:
            with self.subTest(label=label):
                candidate=parse_message('《数字图像处理》作业1：BMP文件的读写\n'+label+'：2026-10-12 10:41',AT)[0]
                self.assertIsNone(candidate['deadline'])

    def test_explicit_deadline_is_preserved_even_before_publication(self):
        for text,expected in [
            ('作业一，开始时间：2026-10-12 10:41\n截止时间：2026-10-30 18:00','2026-10-30T18:00:00+08:00'),
            ('作业一，发布时间：2026-10-12 10:45，截止时间：2026-10-12 10:41',START),
            ('作业一，2026-10-30 18:00前提交报告','2026-10-30T18:00:00+08:00'),
        ]:
            with self.subTest(text=text):self.assertEqual(parse_message(text,AT,'数字图像处理')[0]['deadline'],expected)

    def test_stale_start_only_proposal_cannot_supply_related_task_deadline(self):
        n,p=self.stale()
        task=ingest_web_message(self.box,dict(kind='task_center',message_id='task_one',title='作业1：BMP文件的读写',text='请完成实验报告。',course='数字图像处理',conversation='数字图像处理',captured_at='2026-10-25T10:00:00+08:00',task_type='assignment',deadline=None,detail_state='read',url='https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=3'))
        shown=next(x for x in self.box.proposals() if x['id']==task['proposals'][0]['id'])
        self.assertIsNone(shown['candidate']['deadline']);self.assertEqual(shown['deadline_references'],[])
        legacy=next(x for x in self.box.proposals() if x['id']==p['id'])
        self.assertIsNone(legacy['candidate']['deadline'])
        confirmed=self.box.confirm(p['id']);self.assertIsNone(confirmed['deadline'])
        self.assertEqual(self.box.message(n['message']['id'])['text'],n['message']['text'])

    def test_explicit_repair_clears_only_proven_misclassified_date_and_keeps_audit(self):
        from courseinbox.date_roles import correct_task
        n=self.notice();task=self.box.confirm(n['proposals'][0]['id'])
        with self.box.connection() as db:
            task.update(deadline=START,date_precision='minute',deadline_basis=dict(message_id=n['message']['id'],deadline=START))
            self.box._save_task(db,task)
        result=correct_task(self.box,task['id'],task['version'])
        self.assertIsNone(result['deadline']);self.assertNotIn('deadline_basis',result)
        self.assertEqual(result['version'],task['version']+1);self.assertEqual(result['status'],task['status'])
        detail=self.box.task_detail(task['id']);self.assertEqual(detail['history'][0]['action'],'deadline_misclassification_corrected')
        self.assertEqual(detail['sources'][0]['text'],n['message']['text'])
        with self.assertRaises(Conflict):correct_task(self.box,task['id'],task['version'])

    def test_explicit_repair_refuses_a_real_deadline_or_unproven_date(self):
        from courseinbox.date_roles import correct_task
        n=self.notice();task=self.box.confirm(n['proposals'][0]['id'])
        with self.box.connection() as db:
            task.update(deadline='2026-10-30',date_precision='date');self.box._save_task(db,task)
        with self.assertRaises(Conflict):correct_task(self.box,task['id'],task['version'])
        self.assertEqual(self.box.tasks()[0]['deadline'],'2026-10-30')


if __name__=='__main__':unittest.main()
