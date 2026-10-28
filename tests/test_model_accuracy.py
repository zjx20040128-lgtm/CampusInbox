"""Evidence-based model guardrails, using deterministic fake tool responses."""
import tempfile
import unittest
from pathlib import Path
from courseinbox.agent import Agent
from courseinbox.core import Inbox,parse_message
from courseinbox.chaoxing import parse_notice_candidates
from tests.test_agent import FakeProvider,reply,call

AT='2026-09-17T14:58:00+08:00'

class ModelAccuracyTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.box=Inbox(Path(tmp.name)/'test.sqlite3')

    def analyze(self,text,args,baseline=None):
        provider=FakeProvider([reply([call('propose_task',dict(course='课程甲',evidence=text)|args)]),reply(content='完成')])
        return Agent(self.box,provider).analyze(text,AT,'课程甲','一班',rule_candidates=baseline)

    def test_preparation_alias_does_not_duplicate_notice_task(self):
        text='《课程甲》第一堂课通知\n大家好！明天上课需要绘图，请大家带着电脑或者纸和笔。'
        external=dict(kind='course_notice',title='《课程甲》第一堂课通知',notice_body=text.split('\n',1)[1],attachments=[])
        baseline=parse_notice_candidates(external,AT,'课程甲','一班')
        for title in ('上课准备','绘图准备','带着电脑或者纸和笔'):
            with self.subTest(title=title):
                result=self.analyze(text,dict(title=title,requirements=['请大家带着电脑或者纸和笔']),baseline)
                self.assertEqual(len(result['candidates']),1)
                self.assertEqual(result['candidates'][0]['title'],baseline[0]['title'])
                self.assertEqual(self.box.tasks(),[])

    def test_course_prefix_alias_does_not_duplicate_named_task(self):
        text='《课程甲》实验一：请提交报告。'
        result=self.analyze(text,dict(title='《课程甲》实验一'))
        self.assertEqual(len(result['candidates']),1)

    def test_distinct_explicit_task_is_not_merged(self):
        text='实验一：请提交报告。实验二：请提交源代码。'
        first=parse_message(text,AT,'课程甲','一班')[:1]
        result=self.analyze(text,dict(title='实验二',requirements=['请提交源代码']),first)
        self.assertEqual({c['title'] for c in result['candidates']},{'实验一','实验二'})

    def test_independent_reading_task_survives(self):
        text='实验一：请提交报告。另外请阅读第二章，准备讨论。'
        first=parse_message('实验一：请提交报告。',AT,'课程甲','一班')
        result=self.analyze(text,dict(title='阅读第二章',requirements=['请阅读第二章']),first)
        self.assertEqual(len(result['candidates']),2)

    def test_model_cannot_cancel_without_cancellation_in_evidence(self):
        result=self.analyze('实验一：请提交报告。',dict(title='实验一',operation='cancel'))
        self.assertIn('error',result['trace'][0]['result'])
        self.assertEqual(result['candidates'][0]['operation'],'create')

    def test_model_cannot_update_without_change_in_evidence(self):
        result=self.analyze('实验一：请提交报告。',dict(title='实验一',operation='update'))
        self.assertIn('error',result['trace'][0]['result'])

    def test_real_extension_is_accepted(self):
        result=self.analyze('实验一延期到2026年9月20日18:00。',dict(title='实验一',operation='update',deadline='2026-09-20T18:00:00+08:00',deadline_evidence='延期到2026年9月20日18:00'))
        self.assertNotIn('error',result['trace'][0]['result'])
        self.assertEqual(result['candidates'][0]['operation'],'update')

    def test_negated_changes_do_not_authorize_model_operations(self):
        for text,operation in [('实验一不要取消，仍需提交报告。','cancel'),('实验一不用修改，按原要求提交。','update')]:
            with self.subTest(text=text):
                result=self.analyze(text,dict(title='实验一',operation=operation))
                self.assertIn('error',result['trace'][0]['result'])

    def test_real_cancellation_is_accepted(self):
        result=self.analyze('实验一现已取消。',dict(title='实验一',operation='cancel'))
        self.assertNotIn('error',result['trace'][0]['result'])

    def test_preparation_in_other_class_stays_separate(self):
        text='明天上课绘图，请大家带着电脑或者纸和笔。'
        baseline=parse_message(text,AT,'课程甲','二班')
        result=self.analyze(text,dict(title='绘图准备'),baseline)
        self.assertEqual(len(result['candidates']),2)

    def test_missing_deadline_is_not_reported_as_model_failure(self):
        result=self.analyze('课前请带好彩笔。',dict(title='携带彩笔'),[])
        self.assertIsNone(result['candidates'][0]['deadline'])
        self.assertFalse(any('未识别截止' in w for w in result['candidates'][0]['warnings']))

    def test_publication_date_is_not_a_task_deadline(self):
        text='发布时间：2026年9月17日10:00。实验一：请提交报告，截止时间另行通知。'
        result=self.analyze(text,dict(title='实验一',deadline='2026-09-17T10:00:00+08:00',deadline_evidence='2026年9月17日10:00'),[])
        self.assertEqual(len(result['candidates']),1)
        self.assertIsNone(result['candidates'][0]['deadline'])

    def test_exam_start_is_not_a_deadline(self):
        text='期末考试开始时间：2026年9月22日09:00。请准时参加考试。'
        result=self.analyze(text,dict(title='期末考试',kind='exam',deadline='2026-09-22T09:00:00+08:00',deadline_evidence='2026年9月22日09:00'),[])
        self.assertIsNone(result['candidates'][0]['deadline'])

    def test_deadline_from_other_task_is_not_accepted(self):
        text='实验一：截止2026年9月20日18:00。实验二：截止2026年9月22日18:00。'
        result=self.analyze(text,dict(title='实验二',deadline='2026-09-20T18:00:00+08:00',deadline_evidence='2026年9月20日18:00'),[])
        self.assertIsNone(result['candidates'][0]['deadline'])

    def test_narrative_about_research_is_not_a_new_student_task(self):
        text='老师已提交实验报告，并发表了一篇论文，请知悉。'
        result=self.analyze(text,dict(title='论文任务'),[])
        self.assertEqual(result['candidates'],[])
        self.assertIn('error',result['trace'][0]['result'])

    def test_cancelling_one_material_does_not_cancel_whole_task(self):
        text='实验一取消纸质版报告，仍需上传电子版。'
        result=self.analyze(text,dict(title='实验一',operation='cancel'),[])
        self.assertEqual(result['candidates'],[])

    def test_negated_extension_does_not_authorize_update(self):
        result=self.analyze('实验一无需延期，保持原截止。',dict(title='实验一',operation='update'),[])
        self.assertEqual(result['candidates'],[])

    def test_model_can_still_add_real_reading_task(self):
        result=self.analyze('请阅读本章案例，课堂上分享看法。',dict(title='案例阅读',requirements=['请阅读本章案例']),[])
        self.assertEqual(len(result['candidates']),1)

    def test_dated_submission_is_still_valid(self):
        text='实验二请于2026年9月22日18:00前提交报告。'
        result=self.analyze(text,dict(title='实验二',deadline='2026-09-22T18:00:00+08:00',deadline_evidence='2026年9月22日18:00'),[])
        self.assertEqual(result['candidates'][0]['deadline'],'2026-09-22T18:00:00+08:00')

    def test_negated_student_instruction_is_not_new_work(self):
        result=self.analyze('请不要撰写论文，这条仅供知悉。',dict(title='撰写论文'),[])
        self.assertEqual(result['candidates'],[])

    def test_cancellation_of_other_task_is_not_accepted(self):
        text='实验一：请照常提交报告。实验二现已取消。'
        result=self.analyze(text,dict(title='实验一',operation='cancel'),[])
        self.assertEqual(result['candidates'],[])

    def test_wrong_submission_channel_is_removed(self):
        text='实验一：请通过邮件提交报告。'
        result=self.analyze(text,dict(title='实验一',submission_method='学习通上传',submission_evidence='邮件提交'),[])
        self.assertEqual(result['candidates'][0]['submission_method'],'')

    def test_other_task_requirements_are_not_borrowed(self):
        text='实验一：请提交报告。实验二：请提交源代码。'
        result=self.analyze(text,dict(title='实验一',requirements=['请提交报告','请提交源代码']),[])
        self.assertEqual(result['candidates'][0]['requirements'],['请提交报告'])

    def test_long_single_task_keeps_late_deadline_evidence(self):
        text='实验一：请提交报告。'+('说明文字。'*250)+'截止2026年9月22日18:00。'
        result=self.analyze(text,dict(title='实验一',deadline='2026-09-22T18:00:00+08:00',deadline_evidence='2026年9月22日18:00'),[])
        self.assertEqual(result['candidates'][0]['deadline'],'2026-09-22T18:00:00+08:00')

    def test_exchange_report_announcement_is_not_a_command_to_submit(self):
        result=self.analyze('交流报告已发布，请知悉。',dict(title='报告阅读'),[])
        self.assertEqual(result['candidates'],[])

    def test_scheduled_exam_is_still_new_work(self):
        result=self.analyze('下周五举行期末考试。',dict(title='期末考试',kind='exam'),[])
        self.assertEqual(len(result['candidates']),1)
        self.assertIsNone(result['candidates'][0]['deadline'])

    def test_descriptive_task_title_keeps_the_right_deadline(self):
        text='实验一：请提交报告，截止2026年9月20日18:00。实验二：请提交源码，截止2026年9月22日18:00。'
        for title in ('实验二：提交源码','实验二提交源码'):
            with self.subTest(title=title):
                result=self.analyze(text,dict(title=title,deadline='2026-09-22T18:00:00+08:00',deadline_evidence='2026年9月22日18:00'),[])
                self.assertEqual(result['candidates'][0]['title'],'实验二')
                self.assertEqual(result['candidates'][0]['deadline'],'2026-09-22T18:00:00+08:00')

    def test_extraction_does_not_depend_on_existing_task_query(self):
        p=FakeProvider([reply(content='无需补充')])
        Agent(self.box,p).analyze('请阅读第二章。',AT,'课程甲','一班',rule_candidates=[])
        self.assertEqual([t['function']['name'] for t in p.seen[0][1]],['propose_task'])

    def test_invalid_rule_publication_date_is_corrected_only_in_draft(self):
        text='实验一：请提交报告。发布时间：2026年9月17日10:00。截止时间：2026年9月20日18:00。'
        baseline=parse_message(text,AT,'课程甲','一班')
        baseline[0].update(deadline='2026-09-17T10:00:00+08:00',deadline_evidence='2026年9月17日10:00')
        result=self.analyze(text,dict(title='实验一',deadline='2026-09-20T18:00:00+08:00',deadline_evidence='2026年9月20日18:00'),baseline)
        candidate=result['candidates'][0]
        self.assertEqual(candidate['deadline'],'2026-09-20T18:00:00+08:00')
        self.assertEqual(candidate['model_review'][0]['rule'],'2026-09-17T10:00:00+08:00')
        self.assertEqual(candidate['model_review'][0]['resolution'],'evidence_corrected')
        self.assertEqual(baseline[0]['deadline'],'2026-09-17T10:00:00+08:00')
        saved=self.box.ingest(text,captured_at=AT,course='课程甲',scope='一班',candidates=[candidate])
        self.assertEqual(saved['proposals'][0]['candidate']['model_review'],candidate['model_review'])
        self.assertEqual(self.box.tasks(),[])

    def test_valid_structured_rule_value_is_not_overwritten_on_disagreement(self):
        text='实验一：请提交报告，截止2026年9月20日18:00。'
        baseline=parse_message(text,AT,'课程甲','一班')
        baseline[0].update(deadline='2026-09-21T18:00:00+08:00',field_evidence={'deadline':'平台结束时间：2026-09-21 18:00'})
        result=self.analyze(text,dict(title='实验一',deadline='2026-09-20T18:00:00+08:00',deadline_evidence='2026年9月20日18:00'),baseline)
        candidate=result['candidates'][0]
        self.assertEqual(candidate['deadline'],'2026-09-21T18:00:00+08:00')
        self.assertEqual(candidate['model_review'][0]['resolution'],'needs_review')
        self.assertEqual(candidate['model_review'][0]['model'],'2026-09-20T18:00:00+08:00')

    def test_omitted_deadline_argument_is_derived_from_verified_date_quote(self):
        text='实验一：请提交报告。发布时间：2026年9月17日10:00。截止时间：2026年9月20日18:00。'
        baseline=parse_message(text,AT,'课程甲','一班')
        baseline[0].update(deadline='2026-09-17T10:00:00+08:00',deadline_evidence='2026年9月17日10:00')
        result=self.analyze(text,dict(title='实验一',deadline_evidence='2026年9月20日18:00'),baseline)
        self.assertEqual(result['candidates'][0]['deadline'],'2026-09-20T18:00:00+08:00')

    def test_omitted_deadline_cannot_be_filled_from_publication_quote(self):
        result=self.analyze('实验一：请提交报告。发布时间：2026年9月17日10:00。',dict(title='实验一',deadline_evidence='2026年9月17日10:00'),[])
        self.assertIsNone(result['candidates'][0]['deadline'])

    def test_explicit_unannounced_deadline_clears_a_misclassified_publication_in_draft(self):
        text='实验一：请提交报告。发布时间：2026年9月17日10:00。截止时间另行通知。'
        baseline=parse_message(text,AT,'课程甲','一班')
        baseline[0].update(deadline='2026-09-17T10:00:00+08:00',deadline_evidence='2026年9月17日10:00')
        result=self.analyze(text,dict(title='实验一',deadline=None),baseline)
        c=result['candidates'][0]
        self.assertIsNone(c['deadline'])
        self.assertEqual(c['model_review'][0]['resolution'],'evidence_corrected')
        self.assertIsNone(c['model_review'][0]['model'])
        self.assertIn('截止时间另行通知',c['model_review'][0]['evidence'])

    def test_model_null_does_not_remove_existing_deadline_without_explicit_unannounced_statement(self):
        text='实验一：请提交报告，截止2026年9月20日18:00。'
        result=self.analyze(text,dict(title='实验一',deadline=None))
        self.assertEqual(result['candidates'][0]['deadline'],'2026-09-20T18:00:00+08:00')

    def test_unannounced_statement_cannot_erase_structured_or_other_explicit_due_evidence(self):
        text='实验一：请提交报告。发布时间：2026年9月17日10:00。截止时间另行通知。'
        for extra,fields in [('',{'deadline':'平台结束时间：2026-09-20 18:00'}),('请于2026年9月20日前提交报告。',{})]:
            baseline=parse_message(text+extra,AT,'课程甲','一班')
            baseline[0].update(deadline='2026-09-17T10:00:00+08:00',deadline_evidence='2026年9月17日10:00',field_evidence=fields)
            result=self.analyze(text+extra,dict(title='实验一',deadline=None),baseline)
            self.assertEqual(result['candidates'][0]['deadline'],'2026-09-17T10:00:00+08:00')
