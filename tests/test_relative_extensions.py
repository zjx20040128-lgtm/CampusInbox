import tempfile
import unittest
from pathlib import Path
from courseinbox.core import Inbox,Conflict,ValidationError,parse_message

AT='2026-10-25T10:00:00+08:00'


class RelativeExtensionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.box=Inbox(Path(tmp.name)/'db.sqlite3')

    def task(self,title='实验报告一',due='2026-10-30T18:00:00+08:00',course='数据库',scope='一班'):
        text=f'{title}：请提交报告。'
        c=parse_message(text,'2026-10-23T10:00:00+08:00',course,scope)[0]
        c.update(title=title,deadline=due,requirements=['报告'],matchable=True)
        draft=self.box.ingest(text,course=course,scope=scope,captured_at='2026-10-23T10:00:00+08:00',candidates=[c])['proposals'][0]
        return self.box.confirm(draft['id'])

    def extend(self,text='上次报告再延三天',**kwargs):
        return self.box.ingest(text,course=kwargs.pop('course','数据库'),scope=kwargs.pop('scope','一班'),captured_at=kwargs.pop('captured_at',AT),**kwargs)

    def test_unique_report_calculates_from_existing_deadline_and_waits_for_confirmation(self):
        original=self.task()
        result=self.extend();p=result['proposals'][0];c=p['candidate']
        self.assertEqual(p['target_id'],original['id'])
        self.assertEqual(c['operation'],'update')
        self.assertEqual(c['deadline'],'2026-11-02T18:00:00+08:00')
        self.assertEqual(c['relative_deadline']['base_deadline'],original['deadline'])
        self.assertEqual(self.box.task_detail(original['id'])['deadline'],original['deadline'])
        changed=self.box.confirm(p['id'])
        self.assertEqual((changed['id'],changed['deadline']),(original['id'],'2026-11-02T18:00:00+08:00'))
        self.assertEqual(changed['checklist'],original['checklist'])
        self.assertEqual(len(self.box.tasks()),1)

    def test_date_only_stays_date_only_and_hours_need_a_known_time(self):
        self.task(due='2026-10-30')
        p=self.extend('上次报告顺延两天')['proposals'][0]
        self.assertEqual(p['candidate']['deadline'],'2026-11-01')
        self.assertEqual(p['candidate']['date_precision'],'date')
        hours=self.extend('上次报告延期2小时')['proposals'][0]
        self.assertIsNone(hours['candidate']['deadline'])
        with self.assertRaises(ValidationError):self.box.confirm(hours['id'])

    def test_multiple_reports_do_not_choose_the_latest(self):
        self.task('实验报告一');self.task('实验报告二')
        p=self.extend()['proposals'][0]
        self.assertIsNone(p['target_id'])
        self.assertIsNone(p['candidate']['deadline'])
        self.assertEqual(p['candidate']['relative_deadline']['status'],'ambiguous')
        with self.assertRaises(ValidationError):self.box.confirm(p['id'])

    def test_named_task_is_exact_and_class_scoped(self):
        own=self.task('实验一');self.task('实验一',scope='二班')
        p=self.extend('实验一延期3天')['proposals'][0]
        self.assertEqual(p['target_id'],own['id'])
        self.assertEqual(p['candidate']['deadline'],'2026-11-02T18:00:00+08:00')

    def test_missing_course_and_missing_original_deadline_stay_unresolved(self):
        self.task(due=None)
        for kwargs in ({},{'course':''}):
            p=self.extend(**kwargs)['proposals'][0]
            self.assertIsNone(p['candidate']['deadline'])
            with self.assertRaises(ValidationError):self.box.confirm(p['id'])

    def test_version_change_blocks_confirmation(self):
        task=self.task();p=self.extend()['proposals'][0]
        self.box.patch_task(task['id'],dict(status='in_progress',expected_version=task['version']))
        with self.assertRaises(Conflict):self.box.confirm(p['id'])

    def test_reanalysis_and_cross_source_replay_do_not_extend_twice(self):
        task=self.task();first=self.extend();self.box.confirm(first['proposals'][0]['id'])
        fresh=self.box.reanalyze(first['message']['id'])['proposals'][0]
        self.assertEqual(fresh['candidate']['relative_deadline']['status'],'already_applied')
        self.box.confirm(fresh['id'])
        replay=self.extend(source='另一来源')['proposals'][0]
        self.box.confirm(replay['id'])
        self.assertEqual(self.box.task_detail(task['id'])['deadline'],'2026-11-02T18:00:00+08:00')

    def test_newer_distinct_notice_can_extend_again(self):
        task=self.task();first=self.extend();self.box.confirm(first['proposals'][0]['id'])
        second=self.extend('上次报告再延两天',captured_at='2026-10-26T10:00:00+08:00')['proposals'][0]
        self.assertEqual(second['candidate']['deadline'],'2026-11-04T18:00:00+08:00')
        self.box.confirm(second['id'])
        self.assertEqual(self.box.task_detail(task['id'])['deadline'],'2026-11-04T18:00:00+08:00')

    def test_negative_conditional_and_questions_never_get_a_computed_extension(self):
        task=self.task()
        for text in ('实验一不要延期三天','如果实验一延期三天','实验一能否延期三天？','申请实验一延期三天'):
            for p in self.extend(text)['proposals']:
                self.assertNotEqual(p['candidate'].get('relative_deadline',{}).get('status'),'resolved')
        self.assertEqual(self.box.task_detail(task['id'])['deadline'],task['deadline'])

    def test_unknown_publication_keeps_a_reviewable_draft_without_scan_anchor(self):
        from courseinbox.chaoxing import ingest_web_message
        self.task()
        result=ingest_web_message(self.box,dict(kind='course_notice',message_id='unknown-time',title='作业延期通知',url='https://notice.chaoxing.com/pc/notice/unknown-time/detail',text='上次报告再延三天',course='数据库',conversation='一班',captured_at=None,attachments=[]))
        self.assertEqual(len(result['proposals']),1)
        p=result['proposals'][0]
        self.assertIsNone(p['candidate']['deadline'])
        with self.assertRaises(ValidationError):self.box.confirm(p['id'])
        shown=next(x for x in self.box.proposals() if x['id']==p['id'])
        self.assertIsNone(shown['candidate']['deadline'])

    def test_distinct_pending_extensions_remain_separate_and_refresh_uses_new_version(self):
        self.task()
        first=self.extend()['proposals'][0]
        second=self.extend(captured_at='2026-10-26T10:00:00+08:00')
        self.assertNotEqual(first['id'],second['proposals'][0]['id'])
        self.box.confirm(first['id'])
        with self.assertRaises(Conflict):self.box.confirm(second['proposals'][0]['id'])
        refreshed=self.box.reanalyze(second['message']['id'])['proposals'][0]
        self.assertEqual(refreshed['candidate']['deadline'],'2026-11-05T18:00:00+08:00')

    def test_notice_body_is_resolved_with_original_publication(self):
        from courseinbox.chaoxing import ingest_web_message
        original=self.task()
        result=ingest_web_message(self.box,dict(kind='course_notice',message_id='relative-notice',title='作业延期通知',text='上次报告再延三天',course='数据库',conversation='一班',captured_at=AT,attachments=[],url='https://notice.chaoxing.com/pc/notice/relative-notice/detail'))
        p=result['proposals'][0]
        self.assertEqual(p['target_id'],original['id'])
        self.assertEqual(p['candidate']['deadline'],'2026-11-02T18:00:00+08:00')

    def test_unsupported_relative_prose_cannot_be_confirmed_as_a_new_task(self):
        self.task()
        p=self.extend('上次报告再延三天，提交PDF格式。')['proposals'][0]
        self.assertEqual(p['candidate']['operation'],'update')
        self.assertIsNone(p['candidate']['deadline'])
        with self.assertRaises(ValidationError):self.box.confirm(p['id'])

    def test_multi_task_notice_preserves_an_unrelated_new_task(self):
        self.task('实验一')
        result=self.extend('实验一延期3天。实验二：请提交源码，截止2026年11月5日18:00。')
        candidates={p['candidate']['title']:p['candidate'] for p in result['proposals']}
        self.assertEqual(candidates['实验二']['operation'],'create')
        self.assertEqual(candidates['实验二']['deadline'],'2026-11-05T18:00:00+08:00')

    def test_same_published_extension_rephrased_by_another_source_is_not_cumulative(self):
        task=self.task();first=self.extend();self.box.confirm(first['proposals'][0]['id'])
        replay=self.extend('报告顺延3天',source='另一来源')['proposals'][0]
        self.assertEqual(replay['candidate']['relative_deadline']['status'],'already_applied')
        self.box.confirm(replay['id'])
        self.assertEqual(self.box.task_detail(task['id'])['deadline'],'2026-11-02T18:00:00+08:00')

    def test_extension_does_not_become_the_original_task_publication(self):
        from courseinbox.chaoxing import ingest_web_message
        original=ingest_web_message(self.box,dict(kind='task_center',message_id='original',title='实验报告一',text='实验报告一；未交',description='请提交报告',course='数据库',conversation='一班',captured_at='2026-10-23T10:00:00+08:00',published_at=None,deadline='2026-10-30T18:00:00+08:00',task_type='assignment',detail_state='read',field_evidence={'deadline':'结束时间：2026-10-30 18:00'},url='https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=3'))
        task=self.box.confirm(original['proposals'][0]['id'])
        self.assertIsNone(self.box.task_detail(task['id'])['published_at'])
        changed=ingest_web_message(self.box,dict(kind='course_notice',message_id='later',title='延期通知',text='上次报告再延三天',course='数据库',conversation='一班',captured_at=AT,attachments=[],url='https://notice.chaoxing.com/pc/notice/later/detail'))
        self.box.confirm(changed['proposals'][0]['id'])
        self.assertIsNone(self.box.task_detail(task['id'])['published_at'])

    def test_explicit_new_deadline_is_retained_when_notice_also_mentions_a_duration(self):
        task=self.task('实验一')
        p=self.extend('实验一延期3天，新的截止时间：2026年11月2日18:00。')['proposals'][0]
        self.assertEqual(p['target_id'],task['id'])
        self.assertEqual(p['candidate']['deadline'],'2026-11-02T18:00:00+08:00')

    def test_relative_arithmetic_is_performed_by_server_without_a_model_guess(self):
        from courseinbox.agent import Agent
        from tests.test_agent import FakeProvider,reply
        self.task();provider=FakeProvider([reply(content='不应被调用')])
        result=Agent(self.box,provider).analyze('上次报告再延三天',AT,'数据库','一班')
        self.assertEqual(provider.seen,[])
        self.assertIsNone(result['candidates'][0]['deadline'])
        p=self.extend(candidates=result['candidates'])['proposals'][0]
        self.assertEqual(p['candidate']['deadline'],'2026-11-02T18:00:00+08:00')

    def test_distinct_ambiguous_extensions_are_not_merged(self):
        self.task('实验报告一');self.task('实验报告二')
        first=self.extend()['proposals'][0]
        second=self.extend('上次报告再延两天',captured_at='2026-10-26T10:00:00+08:00')['proposals'][0]
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(len(self.box.proposals()),2)
