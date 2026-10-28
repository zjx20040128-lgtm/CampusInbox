import tempfile
import unittest
from pathlib import Path
from courseinbox.agent import Agent
from courseinbox.core import Inbox,parse_message
from tests.test_agent import FakeProvider,reply

AT='2026-10-25T10:00:00+08:00'
TEXT='课程名称：数据库\n作业名称：实验一\n截止时间：2026-10-30 18:00'


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.box=Inbox(Path(tmp.name)/'db.sqlite3')

    def test_complete_template_preserves_draft_without_model_call(self):
        provider=FakeProvider([reply(content='无需补充')])
        result=Agent(self.box,provider).analyze(TEXT,AT,'数据库','一班')
        self.assertEqual(provider.seen,[])
        self.assertEqual(result['candidates'][0]['deadline'],'2026-10-30T18:00:00+08:00')
        self.assertEqual(result['trace'][0]['result']['route'],'rules_verified')
        self.assertEqual(self.box.tasks(),[])

    def test_conditions_extra_prose_relative_dates_and_multiple_names_use_model(self):
        for text in (TEXT+'\n补交同学除外。',TEXT.replace('2026-10-30 18:00','明天18:00'),TEXT.replace('实验一','实验一和实验二'),TEXT+'\n截止时间：2026-11-01',TEXT.replace('截止时间','开始时间')):
            with self.subTest(text=text):
                provider=FakeProvider([reply(content='无需补充')])
                Agent(self.box,provider).analyze(text,AT,'数据库','一班')
                self.assertTrue(provider.seen)

    def test_incorrect_rule_value_never_bypasses_model_verification(self):
        baseline=parse_message(TEXT,AT,'数据库','一班')
        baseline[0]['deadline']='2026-10-29T18:00:00+08:00'
        provider=FakeProvider([reply(content='核查')])
        Agent(self.box,provider).analyze(TEXT,AT,'数据库','一班',rule_candidates=baseline)
        self.assertTrue(provider.seen)

    def test_incorrect_kind_and_hidden_submission_instructions_use_model(self):
        baseline=parse_message(TEXT,AT,'数据库','一班')
        baseline[0]['kind']='exam'
        provider=FakeProvider([reply(content='核查')])
        Agent(self.box,provider).analyze(TEXT,AT,'数据库','一班',rule_candidates=baseline)
        self.assertTrue(provider.seen)
        conditional=TEXT+'\n提交方式：学习通上传，补交同学除外'
        baseline=parse_message(conditional,AT,'数据库','一班')
        baseline[0]['submission_method']='学习通上传，补交同学除外'
        provider=FakeProvider([reply(content='核查')])
        Agent(self.box,provider).analyze(conditional,AT,'数据库','一班',rule_candidates=baseline)
        self.assertTrue(provider.seen)
