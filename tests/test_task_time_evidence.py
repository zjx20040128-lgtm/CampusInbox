import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox,Conflict
from courseinbox.chaoxing import ingest_web_message

class TaskTimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        clock=patch('courseinbox.core.now_iso',return_value='2026-10-24T14:00:00+08:00');clock.start();self.addCleanup(clock.stop)
        self.box=Inbox(Path(self.tmp.name)/'db.sqlite3')

    def notice(self,number='n1',deadline='2026-10-28 23:35',published='2026-10-23T23:36:00+08:00',extension=False):
        text='课程名称：课程甲\n作业名称：第一次作业\n'+('第一次作业延期至'+deadline if extension else '开始时间：2026-10-23 23:35\n结束时间：'+deadline)
        return ingest_web_message(self.box,dict(kind='course_notice',message_id=number,title='作业:《课程甲》第一次作业',text=text,course='课程甲',conversation='一班',captured_at=published,url=f'https://notice.chaoxing.com/pc/notice/{number}/detail',attachments=[]))

    def raw(self,number='t1',work='3',deadline=None,published=None,media=0):
        return dict(kind='task_center',message_id=number,title='第一次作业',text='第一次作业；未交\n作答时间:10-23 23:35至10-28 23:35',description='完成报告',course='课程甲',conversation='一班',captured_at='2026-10-24T12:00:00+08:00',published_at=published,task_type='assignment',deadline=deadline,platform_status='未交',url=f'https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId={work}',detail_state='read',media_pending_count=media,field_evidence={'title':'第一次作业','deadline':'作答时间:10-23 23:35至10-28 23:35'})

    def displayed(self,p):return next(x for x in self.box.proposals() if x['id']==p['id'])


    def test_published_year_resolves_answer_window_end_not_start(self):
        raw=self.raw(published='2026-10-23T23:36:00+08:00')
        result=ingest_web_message(self.box,raw)
        self.assertEqual(result['message']['external']['deadline'],'2026-10-28T23:35:00+08:00')
        self.assertEqual(self.displayed(result['proposals'][0])['candidate']['deadline'],'2026-10-28T23:35:00+08:00')

    def test_answer_window_crosses_year_and_rejects_missing_or_distant_basis(self):
        from courseinbox.task_window import deadline_from_window
        value='作答时间：12-30 18:00至01-03 20:00'
        self.assertEqual(deadline_from_window(value,'2026-12-29T12:00:00+08:00'),'2027-01-03T20:00:00+08:00')
        self.assertIsNone(deadline_from_window(value,None))
        self.assertIsNone(deadline_from_window(value,'2026-06-01T12:00:00+08:00'))
        self.assertEqual(deadline_from_window('作答时间：2026-12-30 18:00至01-03 20:00',None),'2027-01-03T20:00:00+08:00')
        for bad in ['作答时间：02-30 18:00至03-03 20:00','作答时间：10-23 25:00至10-28 20:00','开始时间：10-23 18:00','剩余12小时']:
            self.assertIsNone(deadline_from_window(bad,'2026-10-23T12:00:00+08:00'))

    def test_absolute_deadline_does_not_require_publication(self):
        n=self.notice(published=None)
        self.assertEqual(n['proposals'][0]['candidate']['deadline'],'2026-10-28T23:35:00+08:00')
        self.assertFalse(n['message']['external']['time_known'])
        self.assertIsNone(self.displayed(n['proposals'][0])['candidate']['published_at'])

    def test_automatic_parser_never_uses_scan_time_as_publication(self):
        from courseinbox.intake_policy import automatic_candidate
        message=dict(text='作业截止明天18:00',captured_at='2026-10-24T12:00:00+08:00',external={'platform':'chaoxing-web','kind':'course_notice','time_known':False})
        candidate=dict(deadline='2026-10-25T18:00:00+08:00',evidence=message['text'],warnings=[])
        self.assertIsNone(automatic_candidate(candidate,message)['deadline'])
        message['text']='作业截止2026-01-01 18:00'
        candidate.update(evidence=message['text'])
        actual=automatic_candidate(candidate,message)
        self.assertEqual(actual['deadline'],'2026-01-01T18:00:00+08:00')
        self.assertFalse(any('早于消息发布时间' in w for w in actual['warnings']))

    def test_relative_deadline_without_publication_is_not_anchored_to_detection(self):
        n=self.notice(deadline='明天晚上八点',published=None)
        self.assertTrue(all(not p['candidate']['deadline'] for p in n['proposals']))

    def test_unknown_publication_absolute_notice_can_be_reanalyzed(self):
        n=self.notice(published=None)
        result=self.box.reanalyze(n['message']['id'])
        self.assertEqual(result['proposals'][0]['candidate']['deadline'],'2026-10-28T23:35:00+08:00')

    def test_candidate_cannot_supply_its_own_time_basis(self):
        n=self.notice();candidate=dict(n['proposals'][0]['candidate'],deadline_basis={'message_id':n['message']['id'],'deadline':'2026-10-28T23:35:00+08:00','published_at':'2099-01-01T00:00:00+08:00'})
        result=self.box.ingest('人工输入的作业日期',course='课程甲',scope='一班',candidates=[dict(candidate,evidence='人工输入的作业日期')])
        self.assertNotIn('deadline_basis',self.displayed(result['proposals'][0])['candidate'])

    def test_notice_and_list_are_aggregated_in_either_arrival_order(self):
        for order in ('notice_first','list_first'):
            with self.subTest(order=order):
                self.setUp()
                if order=='notice_first':n=self.notice();r=ingest_web_message(self.box,self.raw())
                else:r=ingest_web_message(self.box,self.raw());n=self.notice()
                p=self.displayed(r['proposals'][0]);self.assertEqual(p['candidate']['deadline'],'2026-10-28T23:35:00+08:00')
                task=self.box.confirm(p['id']);detail=self.box.task_detail(task['id'])
                self.assertEqual(task['deadline'],'2026-10-28T23:35:00+08:00')
                self.assertEqual(detail['published_at'],'2026-10-23T23:36:00+08:00')
                self.assertIn(n['message']['id'],{m['id'] for m in detail['sources']})

    def test_ignored_notice_never_auto_fills_candidate(self):
        n=self.notice();self.box.dismiss(n['proposals'][0]['id'])
        p=ingest_web_message(self.box,self.raw())['proposals'][0]
        self.assertIsNone(self.displayed(p)['candidate']['deadline'])

    def test_different_month_day_fragment_is_not_overruled_by_notice(self):
        self.notice()
        raw=self.raw();raw['field_evidence']['deadline']='作答时间:10-23 23:35至10-29 23:35'
        p=ingest_web_message(self.box,raw)['proposals'][0]
        self.assertIsNone(self.displayed(p)['candidate']['deadline'])

    def test_conflicting_dates_and_duplicate_platform_ids_require_review(self):
        self.notice();self.notice('n2','2026-10-29 23:35')
        p=ingest_web_message(self.box,self.raw())['proposals'][0]
        self.assertIsNone(self.displayed(p)['candidate']['deadline'])
        with tempfile.TemporaryDirectory() as tmp:
            self.box=Inbox(Path(tmp)/'other.sqlite3');self.notice()
            p=ingest_web_message(self.box,self.raw())['proposals'][0]
            ingest_web_message(self.box,self.raw('t2','4'))
            self.assertIsNone(self.displayed(p)['candidate']['deadline'])

    def test_scan_time_cannot_block_a_real_published_extension(self):
        r=ingest_web_message(self.box,self.raw(deadline='2026-10-28T23:35:00+08:00'))
        task=self.box.confirm(r['proposals'][0]['id'])
        n=self.notice(deadline='2026-10-29 23:35',published='2026-10-24T11:00:00+08:00',extension=True)
        updated=self.box.confirm(n['proposals'][0]['id'])
        self.assertEqual(updated['id'],task['id']);self.assertEqual(updated['deadline'],'2026-10-29T23:35:00+08:00')

    def test_actual_older_publication_is_still_blocked(self):
        r=ingest_web_message(self.box,self.raw(deadline='2026-10-28T23:35:00+08:00',published='2026-10-24T12:00:00+08:00'))
        self.box.confirm(r['proposals'][0]['id'])
        n=self.notice(deadline='2026-10-29 23:35',published='2026-10-24T11:00:00+08:00',extension=True)
        with self.assertRaises(Conflict):self.box.confirm(n['proposals'][0]['id'])

    def test_stable_task_identity_takes_priority_over_changed_display_name(self):
        first=ingest_web_message(self.box,self.raw(deadline='2026-10-28T23:35:00+08:00',published='2026-10-23T23:35:00+08:00'))
        self.box.confirm(first['proposals'][0]['id'])
        changed=self.raw('renamed');changed.update(title='更新后的作业标题',text='更新后的作业标题；未交',field_evidence={'title':'更新后的作业标题'})
        result=ingest_web_message(self.box,changed)
        self.assertEqual(self.displayed(result['proposals'][0])['candidate']['deadline'],'2026-10-28T23:35:00+08:00')

    def test_existing_deadline_still_exposes_other_conflicting_notice(self):
        r=ingest_web_message(self.box,self.raw(deadline='2026-10-28T23:35:00+08:00'));task=self.box.confirm(r['proposals'][0]['id'])
        self.notice(deadline='2026-10-29 23:35',extension=True)
        refs=self.box.task_detail(task['id'])['deadline_references']
        self.assertIn('2026-10-29T23:35:00+08:00',{r['deadline'] for r in refs})

    def test_confirmed_deadline_resolves_inventory_time_only(self):
        from courseinbox.desktop_sync import DesktopSync
        sync=DesktopSync(self.box,Path(__file__).resolve().parents[1],autostart=False);self.addCleanup(sync.close);sync.enabled=True
        job=self.raw(media=1)
        sync.receive(dict(type='task_inventory',phase='catalog',courses=[dict(course_id='1',class_id='2',course='课程甲',course_index=1)],truncated=False))
        sync.receive(dict(type='task_inventory',phase='section',course_id='1',class_id='2',kind='assignment',jobs=[job],complete=True))
        sync.receive(dict(type='task_center',job=job));p=self.box.proposals()[0];self.box.confirm(p['id'])
        n=self.notice();self.box.confirm(n['proposals'][0]['id'])
        report=sync.task_inventory();item=report['items'][0]
        self.assertEqual(item['deadline'],'2026-10-28T23:35:00+08:00');self.assertFalse(item['deadline_pending'])
        self.assertEqual(report['deadline_pending'],0);self.assertTrue(item['media_pending'])

    def test_explicit_conflict_resolution_clears_only_reviewed_inventory_version(self):
        from courseinbox.desktop_sync import DesktopSync
        sync=DesktopSync(self.box,Path(__file__).resolve().parents[1],autostart=False);self.addCleanup(sync.close);sync.enabled=True
        sync.receive(dict(type='task_inventory',phase='catalog',courses=[dict(course_id='1',class_id='2',course='课程甲',course_index=1)],truncated=False))
        def deliver(job):
            sync.receive(dict(type='task_inventory',phase='section',course_id='1',class_id='2',kind='assignment',jobs=[job],complete=True))
            sync.receive(dict(type='task_center',job=job))
        deliver(self.raw(deadline='2026-10-28T23:35:00+08:00'))
        task=self.box.confirm(self.box.proposals()[0]['id'])
        deliver(self.raw('changed',deadline='2026-10-29T23:35:00+08:00'))
        p=self.box.proposals()[0];self.box.confirm(p['id'],{'resolution':'current'})
        self.assertFalse(sync.task_inventory()['items'][0]['deadline_pending'])
        deliver(self.raw('another',deadline='2026-10-30T23:35:00+08:00'))
        self.assertTrue(sync.task_inventory()['items'][0]['deadline_pending'])

if __name__=='__main__':unittest.main()
