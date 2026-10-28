import tempfile
import unittest
from pathlib import Path

from courseinbox.core import Inbox, ValidationError, Conflict, NotFound

AT='2026-10-03T09:00:00+08:00'
URL='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=3'


class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.base=self.box.ingest('《软件工程》 第三次作业：请提交实验报告。截止10月12日18:00。',captured_at=AT,scope='一班')
        self.original=self.base['message']

    def tearDown(self):
        self.tmp.cleanup()

    def add(self,text='请同时提交源代码。',**extra):
        return self.box.supplement_message(self.original['id'],dict(text=text,**extra))

    def test_plain_language_requirement_updates_same_task_and_preserves_checks(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        self.box.patch_task(task['id'],{'expected_version':task['version'],'checklist':[True]})
        result=self.add('需使用C++语言编写程序',target='task:'+task['id'])
        self.assertIn('需使用C++语言编写程序',result['proposals'][0]['candidate']['requirements'])
        self.assertEqual(len(self.box.tasks()),1)
        refreshed=self.box.reanalyze(result['message']['id'])['proposals'][0]
        updated=self.box.confirm(refreshed['id'])
        self.assertEqual(updated['id'],task['id'])
        self.assertIn('需使用C++语言编写程序',[x['text'] for x in updated['checklist']])
        self.assertTrue(updated['checklist'][0]['done'])
        self.assertEqual(updated['deadline'],task['deadline'])
        self.assertEqual(len(self.box.tasks()),1)

    def test_mixed_material_and_plain_language_constraints_are_both_retained(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        result=self.add('需使用C++语言。请同时提交源代码。不得使用第三方库。',target='task:'+task['id'])
        requirements=result['proposals'][0]['candidate']['requirements']
        self.assertIn('需使用C++语言',requirements)
        self.assertIn('不得使用第三方库',requirements)
        self.assertTrue(any('源代码' in item for item in requirements))

    def test_only_draft_until_confirmation_and_both_sources_retained(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        before=self.box.task_detail(task['id'])
        result=self.add(target='task:'+task['id'])
        self.assertEqual(self.box.task_detail(task['id']),before)
        self.assertEqual(len(result['proposals']),1)
        confirmed=self.box.confirm(result['proposals'][0]['id'])
        self.assertEqual(confirmed['id'],task['id'])
        self.assertEqual(len(self.box.tasks()),1)
        self.assertTrue(any('源代码' in item['text'] for item in confirmed['checklist']))
        self.assertTrue(any('实验报告' in item['text'] for item in confirmed['checklist']))
        self.assertEqual({m['id'] for m in self.box.task_detail(task['id'])['sources']},{self.original['id'],result['message']['id']})
        self.assertEqual(self.box.message(self.original['id'])['text'],self.original['text'])
        records=self.box.supplement_context(self.original['id'])['records']
        self.assertEqual(records[0]['status'],'confirmed')

    def test_pending_target_is_one_combined_draft_and_not_auto_created(self):
        result=self.add(target='proposal:'+self.base['proposals'][0]['id'])
        self.assertEqual(self.box.tasks(),[])
        self.assertEqual(len(self.box.proposals()),1)
        task=self.box.confirm(result['proposals'][0]['id'])
        self.assertEqual(task['title'],'第三次作业')
        self.assertEqual(len(task['checklist']),2)

    def test_duplicate_request_and_ignored_supplement_do_not_resurrect(self):
        target='proposal:'+self.base['proposals'][0]['id']
        first=self.add(target=target)
        self.box.dismiss(first['proposals'][0]['id'])
        replay=self.add(target=target)
        self.assertTrue(replay['duplicate'])
        self.assertEqual(first['message']['id'],replay['message']['id'])
        self.assertEqual(self.box.proposals(),[])

    def test_unrelated_target_and_unknown_fields_rejected_without_writes(self):
        other=self.box.ingest('《数学》第一次作业请完成习题。',captured_at=AT)
        task=self.box.confirm(other['proposals'][0]['id'])
        before=len(self.box.messages())
        with self.assertRaises(ValidationError):self.add(target='task:'+task['id'])
        with self.assertRaises(ValidationError):self.add(target='auto',automatic=True)
        self.assertEqual(len(self.box.messages()),before)

    def test_relative_deadline_uses_explicit_notice_time_and_requires_confirmation(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        result=self.add('截止时间延期到明天18:00，其他要求不变。',target='task:'+task['id'],reference_at='2026-10-04T10:00:00+08:00')
        self.assertEqual(self.box.task_detail(task['id'])['deadline'],task['deadline'])
        self.assertEqual(result['proposals'][0]['candidate']['deadline'],'2026-10-05T18:00:00+08:00')
        confirmed=self.box.confirm(result['proposals'][0]['id'])
        self.assertEqual(confirmed['deadline'],'2026-10-05T18:00:00+08:00')

    def test_refreshed_supplement_keeps_target_original_and_partial_file_warning(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        result=self.add(target='task:'+task['id'],filename='实验说明.pdf',file_partial=True)
        refreshed=self.box.reanalyze(result['message']['id'])
        self.assertEqual(refreshed['proposals'][0]['target_id'],task['id'])
        self.assertTrue(any('部分' in w for w in refreshed['proposals'][0]['candidate']['warnings']))
        confirmed=self.box.confirm(refreshed['proposals'][0]['id'])
        self.assertEqual(confirmed['id'],task['id'])
        self.assertEqual(len(self.box.task_detail(task['id'])['sources']),2)

    def test_plain_summary_can_add_actual_body_without_replacing_original(self):
        summary=self.box.ingest('您有一条新消息，请点击查看。',captured_at=AT,course='数据库')
        result=self.box.supplement_message(summary['message']['id'],{'text':'《数据库》实验三，请提交实验报告，截止10月20日。','target':'auto'})
        self.assertEqual(len(result['proposals']),1)
        self.assertEqual(self.box.message(summary['message']['id'])['text'],summary['message']['text'])
        self.assertEqual(self.box.tasks(),[])

    def test_empty_or_large_text_and_invalid_time_rejected(self):
        for body in ({'text':''},{'text':'x'*20001},{'text':'补充','reference_at':'bad'},{'text':'补充','file_partial':'true'}):
            with self.subTest(body=str(body)[:40]),self.assertRaises(ValidationError):self.box.supplement_message(self.original['id'],body)

    def test_cleared_original_and_nested_supplement_rejected(self):
        result=self.add(target='proposal:'+self.base['proposals'][0]['id'])
        with self.assertRaises(ValidationError):self.box.supplement_message(result['message']['id'],{'text':'再次补充'})
        self.box.clear_messages([self.original['id']])
        with self.assertRaises((Conflict,NotFound)):self.add()

    def test_old_source_supplement_adds_requirements_without_overwriting_newer_deadline(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        newer=self.box.ingest('《软件工程》第三次作业延期到10月18日18:00。',captured_at='2026-10-04T09:00:00+08:00',scope='一班')
        self.box.confirm(newer['proposals'][0]['id'])
        result=self.add(target='task:'+task['id'])
        confirmed=self.box.confirm(result['proposals'][0]['id'])
        self.assertTrue(any('源代码' in item['text'] for item in confirmed['checklist']))
        self.assertEqual(confirmed['deadline'],'2026-10-18T18:00:00+08:00')

    def test_original_reanalysis_keeps_pending_supplement_content(self):
        result=self.add(target='proposal:'+self.base['proposals'][0]['id'])
        self.box.reanalyze(self.original['id'])
        pending=self.box.proposals()
        self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['id'],result['proposals'][0]['id'])
        self.assertTrue(any('源代码' in item for item in pending[0]['candidate']['requirements']))
        task=self.box.confirm(pending[0]['id'])
        self.assertTrue(any('源代码' in item['text'] for item in task['checklist']))

    def test_auto_replay_after_new_targets_is_idempotent(self):
        message=self.box.ingest('您有一条新消息，请点击查看。',captured_at=AT)['message']
        body={'target':'auto','text':'《数据库》实验三，请提交实验报告。'}
        first=self.box.supplement_message(message['id'],body)
        repeated=self.box.supplement_message(message['id'],body)
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(first['message']['id'],repeated['message']['id'])

    def test_refreshing_older_supplement_preserves_later_composed_evidence(self):
        first=self.add(target='proposal:'+self.base['proposals'][0]['id'])
        second=self.add('请另外提交测试结果。',target='proposal:'+first['proposals'][0]['id'])
        self.box.reanalyze(first['message']['id'])
        pending=self.box.proposals()
        self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['id'],second['proposals'][0]['id'])
        self.assertTrue(any('测试结果' in item for item in pending[0]['candidate']['requirements']))
        refreshed=self.box.reanalyze(second['message']['id'])
        self.assertTrue(any('测试结果' in item for item in refreshed['proposals'][0]['candidate']['requirements']))

    def test_old_supplement_cannot_fill_fields_from_before_latest_source(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        newer=self.box.ingest('《软件工程》第三次作业延期到10月18日18:00。',captured_at='2026-10-04T09:00:00+08:00',scope='一班')
        self.box.confirm(newer['proposals'][0]['id'])
        result=self.add('请同时提交源代码。提交方式：邮件提交。',target='task:'+task['id'])
        with self.assertRaises(Conflict):self.box.confirm(result['proposals'][0]['id'],{'resolution':'incoming'})
        self.assertEqual(self.box.task_detail(task['id'])['submission_method'],task['submission_method'])

    def test_unknown_original_time_never_uses_scan_for_relative_dates(self):
        with self.box.connection() as db:
            import json
            message=self.original|{'external':{'time_known':False}}
            db.execute('UPDATE messages SET data=? WHERE id=?',(json.dumps(message),message['id']))
        from courseinbox.time_evidence import publication
        result=self.add(target='proposal:'+self.base['proposals'][0]['id'])
        self.assertIsNone(publication(result['message']))
        self.assertFalse(self.box.supplement_context(self.original['id'])['reference_known'])
        relative=self.add('截止时间延期到明天18:00。',target='proposal:'+self.base['proposals'][0]['id'])
        self.assertIsNone(relative['proposals'][0]['candidate']['deadline'])
        absolute=self.add('截止时间延期到2026年10月28日18:00。',target='proposal:'+self.base['proposals'][0]['id'])
        self.assertEqual(absolute['proposals'][0]['candidate']['deadline'],'2026-10-28T18:00:00+08:00')

    def test_multiple_targets_require_selection(self):
        original=self.box.ingest('《数学》第一次作业请提交实验报告。第二次作业请提交演示文稿。',captured_at=AT)['message']
        context=self.box.supplement_context(original['id'])
        self.assertGreater(len(context['targets']),1)
        with self.assertRaises(ValidationError):self.box.supplement_message(original['id'],{'text':'请补充源代码。'})

    def test_manual_evidence_does_not_change_automatic_detail_coverage(self):
        from courseinbox.chaoxing import normalize_web_message
        from courseinbox.supplements import inventory_status
        body=dict(kind='task_center',message_id='manual-test',title='实验三',text='请提交实验报告。',course='数据库',conversation='一班',url=URL,captured_at=AT,detail_state='unavailable',attachments=[])
        value=normalize_web_message(body)
        original=self.box.ingest(**value)['message']
        target=self.box.supplement_context(original['id'])['targets'][0]['key']
        result=self.box.supplement_message(original['id'],{'text':'请提交源代码。','target':target,'file_partial':True})
        self.assertEqual(self.box.message(original['id'])['external']['detail_state'],'unavailable')
        self.box.confirm(result['proposals'][0]['id'])
        with self.box.connection() as db:status=inventory_status(db)[original['id']]
        self.assertEqual(status['status'],'confirmed');self.assertTrue(status['file_partial'])
        self.assertEqual(self.box.message(original['id'])['external']['detail_state'],'unavailable')

    def test_manual_supplement_does_not_reuse_older_ordinary_draft(self):
        task=self.box.confirm(self.base['proposals'][0]['id'])
        newer=self.box.ingest('《软件工程》第三次作业请提交实验报告。',captured_at='2026-10-05T09:00:00+08:00',scope='一班')
        self.box.confirm(newer['proposals'][0]['id'])
        ordinary=self.box.ingest('《软件工程》第三次作业请提交实验报告和源代码。截止10月12日18:00。',captured_at='2026-10-04T09:00:00+08:00',scope='一班')
        supplement=self.add(target='task:'+task['id'])
        self.assertNotEqual(supplement['proposals'][0]['id'],ordinary['proposals'][0]['id'])
        confirmed=self.box.confirm(supplement['proposals'][0]['id'])
        self.assertTrue(any('源代码' in item['text'] for item in confirmed['checklist']))

    def test_target_is_required_for_a_stable_replay_key(self):
        with self.assertRaises(ValidationError):self.add()

    def test_legacy_structured_source_without_task_body_can_be_supplemented(self):
        from courseinbox.chaoxing import normalize_web_message
        value=normalize_web_message(dict(kind='task_center',message_id='legacy-supplement',title='实验三',text='请提交实验报告。',course='数据库',conversation='一班',url=URL,captured_at=AT))
        value['external'].pop('task_body',None);value['candidates']=[]
        original=self.box.ingest(**value)['message']
        context=self.box.supplement_context(original['id'])
        self.assertEqual(len(context['targets']),1)
        supplement=self.box.supplement_message(original['id'],dict(text='请同时提交源代码。',target=context['targets'][0]['key']))
        self.assertEqual(len(supplement['proposals']),1)
        self.assertEqual(self.box.message(original['id'])['text'],original['text'])

