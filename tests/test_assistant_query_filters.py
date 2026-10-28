import unittest
from unittest.mock import patch

import test_assistant_status_query as fixtures
from courseinbox.core import ValidationError


class ExtendedAssistantQueryTests(unittest.TestCase):
    def setUp(self):
        fixtures.AssistantStatusQueryTests.setUp(self)
        self.tasks.extend([
            dict(id='tomorrow',title='实验报告',course='C语言程序设计',scope='一班',status='pending',deadline='2026-10-24T18:00:00+08:00'),
            dict(id='next-week',title='图像增强',course='数字图像处理',scope='一班',status='pending',deadline='2026-10-27'),
            dict(id='nov',title='目标检测报告',course='人工智能',scope='一班',status='pending',deadline='2026-11-02'),
        ])

    def titles(self, question, **kwargs):
        answer=self.agent.ask(question, **kwargs)['answer']
        return [line.split(' / ',1)[1].split('：',1)[0] for line in answer.splitlines() if line.startswith('• ')]

    def test_today_tomorrow_and_next_week(self):
        self.assertEqual(self.titles('今天有哪些任务要提交'),['今天全天任务'])
        self.assertEqual(self.titles('明天有哪些任务要提交'),['实验报告'])
        self.assertEqual(self.titles('下周有哪些任务要提交'),['图像增强','未来任务','做完待交任务'])

    def test_future_days_and_date_range(self):
        self.assertEqual(self.titles('未来3天有哪些任务'),['今天全天任务','实验报告'])
        self.assertEqual(self.titles('10月24日至10月28日有哪些任务'),['实验报告','图像增强'])
        self.assertEqual(self.titles('10月24日至28日有哪些任务'),['实验报告','图像增强'])
        self.assertEqual(self.titles('2026-10-24到2026-10-28有哪些任务'),['实验报告','图像增强'])
        self.assertEqual(self.titles('10月24日之前要交什么任务'),['今天全天任务','实验报告'])
        self.assertEqual(self.titles('明天之前有哪些任务'),['今天全天任务','实验报告'])

    def test_course_in_question_and_task_keyword(self):
        self.assertEqual(self.titles('C语言程序设计有哪些任务未提交'),['实验报告'])
        self.assertEqual(self.titles('搜索“图像”相关任务'),['图像增强'])
        self.assertEqual(self.titles('图像增强什么时候交'),['图像增强'])
        self.assertEqual(self.titles('课程：不存在的课程，有哪些任务'),[])

    def test_missing_deadline_and_count(self):
        self.assertEqual(self.titles('哪些任务没有截止时间'),['未知截止任务'])
        answer=self.agent.ask('明天有多少项任务')['answer']
        self.assertIn('1 项',answer)
        self.assertNotIn('• ',answer)

    def test_filters_intersect_instead_of_overriding_scope(self):
        self.mock_tasks.return_value=[t for t in self.tasks if t['course']=='课程一']
        self.assertEqual(self.titles('C语言程序设计有哪些任务',course='课程一'),[])
        self.mock_tasks.assert_called_with('课程一',None)

    def test_unsupported_filter_does_not_silently_list_everything(self):
        answer=self.agent.ask('寒假有哪些任务')['answer']
        self.assertNotIn('• ',answer)
        self.assertIn('未识别',answer)

    def test_first_person_questions_keep_status_date_and_course_filters(self):
        expected=self.titles('有哪些作业没提交？')
        self.assertTrue(expected)
        for question in ('我还有哪些作业没提交？','我的作业还有哪些未提交？'):
            with self.subTest(question=question):
                self.assertEqual(self.titles(question),expected)
        self.assertEqual(self.titles('我明天有哪些任务未提交？'),['实验报告'])
        self.assertEqual(self.titles('我的C语言程序设计还有哪些任务未提交？'),['实验报告'])

    def test_first_person_unknown_conditions_still_do_not_widen_the_query(self):
        for question in ('我寒假有哪些任务','我的高优先级作业有哪些未提交'):
            with self.subTest(question=question):
                answer=self.agent.ask(question)['answer']
                self.assertIn('未识别',answer)
                self.assertNotIn('• ',answer)

    def test_first_person_words_in_course_names_and_keywords_are_preserved(self):
        self.tasks.append(dict(id='personal-name',title='我的任务',course='我的作业',scope='一班',status='pending',deadline=None))
        self.assertEqual(self.titles('我的作业有哪些任务未提交'),['我的任务'])
        self.assertEqual(self.titles('搜索“我的任务”'),['我的任务'])

    def test_specific_date_uses_beijing_calendar_day(self):
        self.assertEqual(self.titles('2026年10月24日有哪些任务'),['实验报告'])
        self.assertEqual(self.titles('10月23日哪些任务已逾期'),['今天已到时任务'])

    def test_invalid_date_and_reversed_explicit_range_are_rejected(self):
        for question in ('2月30日有哪些任务','2026年11月2日到2026年10月24日有哪些任务'):
            with self.subTest(question=question), self.assertRaises(ValidationError):
                self.agent.ask(question)

    def test_year_rollover_and_week_start(self):
        self.tasks.append(dict(id='jan',title='跨年实验',course='课程一',scope='一班',status='pending',deadline='2027-01-02'))
        with patch('courseinbox.agent.now_iso',return_value='2026-12-30T12:00:00+08:00'):
            self.assertEqual(self.titles('12月31日至1月3日有哪些任务'),['跨年实验'])
        self.assertEqual(self.titles('本周有哪些任务'),['今天全天任务','实验报告'])

    def test_course_alias_and_task_kind(self):
        for task in self.tasks:task.setdefault('kind','other')
        self.tasks[-3]['kind']='experiment'
        self.tasks[-2]['kind']='assignment'
        self.tasks[-1]['kind']='project'
        self.assertEqual(self.titles('C语言有哪些任务'),['实验报告'])
        self.assertEqual(self.titles('明天有哪些实验'),['实验报告'])
        self.assertEqual(self.titles('下周有哪些作业'),['图像增强'])

    def test_keyword_status_date_and_sort_can_combine(self):
        self.assertEqual(self.titles('11月搜索“报告”未提交任务'),['目标检测报告'])
        self.assertEqual(self.titles('下周有哪些任务，按截止时间从晚到早排序'),['未来任务','做完待交任务','图像增强'])

    def test_ambiguous_course_alias_is_not_guessed(self):
        self.tasks.append(dict(id='other',title='高级实验',course='C语言高级设计',scope='一班',status='pending',deadline='2026-10-30'))
        with self.assertRaises(ValidationError):self.agent.ask('C语言有哪些任务')

    def test_date_inside_quoted_keyword_is_not_a_deadline_filter(self):
        self.tasks.append(dict(id='named',title='11月读书报告',course='课程一',scope='一班',status='pending',deadline=None))
        self.assertEqual(self.titles('搜索“11月读书报告”'),['11月读书报告'])
