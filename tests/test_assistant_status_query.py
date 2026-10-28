import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox, ValidationError
from courseinbox.agent import Agent


NOW = '2026-10-23T19:00:00+08:00'


class AssistantStatusQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox = Inbox(Path(self.tmp.name) / 'inbox.sqlite3')
        self.agent = Agent(self.inbox)
        self.tasks = [
            dict(id='future',title='未来任务',course='课程一',scope='一班',status='pending',deadline='2026-10-30'),
            dict(id='old',title='逾期任务',course='课程一',scope='一班',status='pending',deadline='2026-10-22'),
            dict(id='submitted',title='已交任务',course='课程一',scope='一班',status='submitted',deadline='2026-10-30'),
            dict(id='cancelled',title='取消任务',course='课程一',scope='一班',status='cancelled',deadline=None),
            dict(id='done',title='做完待交任务',course='课程一',scope='一班',status='done',deadline='2026-10-30'),
            dict(id='today',title='今天全天任务',course='课程一',scope='一班',status='pending',deadline='2026-10-23'),
            dict(id='unknown',title='未知截止任务',course='课程一',scope='一班',status='pending',deadline=None),
            dict(id='hour',title='今天已到时任务',course='课程一',scope='一班',status='pending',deadline='2026-10-23T18:00:00+08:00'),
        ]
        self.mock_tasks = patch.object(self.inbox, 'tasks', return_value=self.tasks).start()
        self.addCleanup(patch.stopall)
        patch('courseinbox.agent.now_iso', return_value=NOW).start()

    def test_unsubmitted_excludes_expired_submitted_and_cancelled(self):
        for question in ('还有哪些任务未提交', '有哪些没交的作业', '哪些作业还没提交'):
            with self.subTest(question=question):
                answer=self.agent.ask(question)['answer']
                for title in ('未来任务','做完待交任务','今天全天任务','未知截止任务'):
                    self.assertIn(title,answer)
                for title in ('逾期任务','已交任务','取消任务','今天已到时任务'):
                    self.assertNotIn('/ '+title+'：',answer)

    def test_submitted_and_overdue_questions_are_not_unsubmitted_queries(self):
        submitted=self.agent.ask('哪些任务已提交')['answer']
        self.assertIn('已交任务',submitted)
        self.assertNotIn('未来任务',submitted)
        overdue=self.agent.ask('哪些任务已经逾期')['answer']
        self.assertIn('逾期任务',overdue)
        self.assertIn('今天已到时任务',overdue)
        self.assertNotIn('今天全天任务',overdue)
        self.assertNotIn('已交任务',overdue)

    def test_model_upcoming_tool_uses_same_filter_and_keeps_scope(self):
        result=self.agent._execute('get_upcoming_tasks',{},'课程一','一班',None,[])
        self.assertEqual({t['id'] for t in result['tasks']},{'future','done','today','unknown'})
        self.mock_tasks.assert_called_with('课程一','一班')

    def test_simple_status_query_cannot_be_overridden_by_model(self):
        self.agent.provider=object()
        result=self.agent.ask('哪些任务未提交')
        self.assertEqual(result['mode'],'rules')
        self.assertNotIn('已交任务',result['answer'])

    def test_query_preserves_business_data(self):
        self.agent.ask('哪些任务未提交',course='课程一',scope='一班')
        self.mock_tasks.assert_called_with('课程一','一班')
        self.assertEqual(self.tasks[2]['status'],'submitted')

    def test_month_query_excludes_other_months_and_unknown_dates(self):
        self.tasks.extend([
            dict(id='nov',title='十一月任务',course='课程一',scope='一班',status='pending',deadline='2026-11-02T08:00:00+08:00'),
            dict(id='next-year',title='明年十一月任务',course='课程一',scope='一班',status='pending',deadline='2027-11-02'),
        ])
        for question in ('11月有哪些任务要提交','十一月有哪些任务要提交','2026年11月有哪些未提交任务'):
            with self.subTest(question=question):
                answer=self.agent.ask(question)['answer']
                self.assertIn('/ 十一月任务：',answer)
                self.assertIn('2026年11月',answer)
                for title in ('未来任务','未知截止任务','明年十一月任务'):
                    self.assertNotIn('/ '+title+'：',answer)
        answer=self.agent.ask('2027年11月有哪些任务要提交')['answer']
        self.assertIn('/ 明年十一月任务：',answer)
        self.assertNotIn('/ 十一月任务：',answer)

    def test_month_combines_with_status_and_scope(self):
        answer=self.agent.ask('10月哪些任务已提交',course='课程一',scope='一班')['answer']
        self.assertIn('/ 已交任务：',answer)
        self.assertNotIn('/ 未来任务：',answer)
        self.mock_tasks.assert_called_with('课程一','一班')

    def test_next_month_crosses_year_and_model_cannot_ignore_it(self):
        self.tasks.append(dict(id='jan',title='跨年任务',course='课程一',scope='一班',status='pending',deadline='2027-01-02'))
        with patch('courseinbox.agent.now_iso', return_value='2026-12-23T19:00:00+08:00'):
            self.agent.provider=object()
            answer=self.agent.ask('下个月有哪些任务要提交')['answer']
        self.assertIn('2027年1月',answer)
        self.assertIn('/ 跨年任务：',answer)
        self.assertNotIn('/ 未知截止任务：',answer)

    def test_invalid_or_multiple_months_do_not_return_unfiltered_tasks(self):
        for question in ('13月有哪些任务', '0月有哪些任务', '10月和11月有哪些任务'):
            with self.subTest(question=question), self.assertRaises(ValidationError):
                self.agent.ask(question)

    def test_month_boundary_uses_beijing_time(self):
        self.tasks.append(dict(id='utc',title='北京时间十一月任务',course='课程一',scope='一班',status='pending',deadline='2026-10-31T18:00:00+00:00'))
        answer=self.agent.ask('11月有哪些任务要提交')['answer']
        self.assertIn('/ 北京时间十一月任务：',answer)
        self.assertIn('2026-11-01 02:00',answer)
        self.assertNotIn('/ 未知截止任务：',answer)
