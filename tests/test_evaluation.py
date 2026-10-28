import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from courseinbox.core import Inbox, ValidationError
from courseinbox.evaluation import evaluate, prepare_labels, local_provider, model_runner


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root / 'inbox.sqlite3'
        self.box = Inbox(self.database)

    def message(self, text, **extra):
        return self.box.ingest(text, captured_at='2026-10-20T12:00:00+08:00', course='数据库', candidates=[], **extra)['message']

    def labels(self, rows, schema=2):
        path = self.root / 'labels.json'
        path.write_text(json.dumps(dict(schema=schema,labels=rows)), encoding='utf-8')
        return path

    def row(self, message, expected, reviewed=True):
        return dict(key=hashlib.sha256(message['id'].encode()).hexdigest()[:24],reviewed=reviewed,expected_tasks=expected)

    def test_multi_task_fields_are_matched_to_the_same_task(self):
        message=self.message('实验三截止10月23日；实验四截止10月25日。')
        labels=self.labels([self.row(message,[dict(title='实验三',deadline='2026-10-23',operation='create'),dict(title='实验四',deadline='2026-10-25',operation='create')])])
        def swapped(message):
            return dict(candidates=[dict(title='实验三',deadline='2026-10-25',operation='create'),dict(title='实验四',deadline='2026-10-23',operation='create')])
        report=evaluate(self.database,labels,runner=swapped)
        self.assertEqual(report['task_precision'],1)
        self.assertEqual(report['deadline_exact'],0)
        self.assertEqual(report['deadline_cases'],2)
        self.assertEqual(report['cases'][0]['error_types'],['wrong_deadline'])
        self.assertNotIn('实验三',json.dumps(report,ensure_ascii=False))

    def test_unreviewed_and_missing_labels_do_not_inflate_scores(self):
        message=self.message('实验三截止10月23日。')
        rows=[self.row(message,[dict(title='实验三',deadline='2026-10-23',operation='create')]),dict(key='f'*24,reviewed=True,expected_tasks=[]),dict(key='a'*24,reviewed=False,expected_tasks=[])]
        report=evaluate(self.database,self.labels(rows))
        self.assertEqual((report['labeled'],report['matched'],report['missing'],report['unreviewed']),(2,1,1,1))
        self.assertFalse(report['target_evidence_complete'])
        self.assertEqual(report['update_cases'],0)
        self.assertIsNone(report['update_recall'])
        self.assertEqual(report['latency_ms']['samples'],1)

    def test_missing_positive_and_invented_deadline_remain_visible_in_metrics(self):
        message=self.message('实验三，请提交报告。')
        rows=[self.row(message,[dict(title='实验三',deadline=None,operation='create')]),dict(key='f'*24,reviewed=True,expected_tasks=[dict(title='实验四',deadline='2026-10-25',operation='update')])]
        def invented(message):return dict(candidates=[dict(title='实验三',deadline='2026-10-23',operation='create')])
        result=evaluate(self.database,self.labels(rows),runner=invented)
        self.assertEqual(result['task_recall'],0.5)
        self.assertEqual(result['deadline_exact'],0)
        self.assertEqual(result['update_recall'],0)
        self.assertEqual(result['unsupported_deadlines'],1)
        self.assertIn('invented_deadline',result['cases'][0]['error_types'])

    def test_verified_template_is_counted_as_skipped_not_model_inference(self):
        from tests.test_agent import FakeProvider,reply
        message=self.message('课程名称：数据库\n作业名称：实验一\n截止时间：2026-10-30 18:00')
        labels=self.labels([self.row(message,[dict(title='实验一',deadline='2026-10-30T18:00:00+08:00',operation='create')])])
        provider=FakeProvider([reply(content='无需补充')])
        report=evaluate(self.database,labels,mode='qwen',runner=model_runner(self.box,provider))
        self.assertEqual(provider.seen,[])
        self.assertEqual(report['routing'],dict(rules=0,rules_verified=1,model_assisted=0,relative_extension=0))
        self.assertEqual(report['cases'][0]['error_types'],[])

    def test_relative_extension_route_is_not_counted_as_a_model_call(self):
        from tests.test_agent import FakeProvider,reply
        m=self.message('上次报告再延三天')
        labels=self.labels([self.row(m,[dict(title='报告',deadline=None,operation='update')])])
        provider=FakeProvider([reply(content='不应调用')])
        report=evaluate(self.database,labels,mode='qwen',runner=model_runner(self.box,provider))
        self.assertEqual(provider.seen,[])
        self.assertEqual(report['routing']['relative_extension'],1)
        self.assertEqual(report['routing']['model_assisted'],0)

    def test_all_rows_are_read_without_the_inbox_500_message_limit(self):
        message=self.message('实验三截止10月23日。')
        with self.box.connection() as db:
            for index in range(510):
                value=dict(message,id='newer-'+str(index),text='普通通知')
                db.execute('INSERT INTO messages(id,fingerprint,data) VALUES(?,?,?)',(value['id'],value['id'],json.dumps(value)))
        labels=self.labels([self.row(message,[dict(title='实验三',deadline='2026-10-23',operation='create')])])
        before=self.database.read_bytes()
        self.assertEqual(evaluate(self.database,labels)['matched'],1)
        self.assertEqual(self.database.read_bytes(),before)

    def test_progress_and_cancellation_do_not_silently_score_partial_runs(self):
        from courseinbox.evaluation import EvaluationCancelled
        message=self.message('实验三截止10月23日。')
        rows=[self.row(message,[dict(title='实验三',deadline='2026-10-23',operation='create')]),dict(key='f'*24,reviewed=True,expected_tasks=[])]
        events=[]
        with self.assertRaises(EvaluationCancelled):
            evaluate(self.database,self.labels(rows),progress=lambda done,total:events.append((done,total)),cancel=lambda:bool(events))
        self.assertEqual(events,[(1,2)])
        events=[]
        report=evaluate(self.database,self.labels(rows),progress=lambda done,total:events.append((done,total)))
        self.assertEqual(events,[(1,2),(2,2)])
        self.assertEqual(report['cases'][0]['deadline_right'],1)

    def test_duplicate_or_invalid_reviewed_labels_are_rejected(self):
        message=self.message('普通通知')
        row=self.row(message,[])
        with self.assertRaises(ValidationError):evaluate(self.database,self.labels([row,row]))
        for expected in ([dict(title='实验三',deadline='2026-02-30',operation='create')],[dict(title='实验三',deadline=None,operation='typo')]):
            with self.assertRaises(ValidationError):evaluate(self.database,self.labels([self.row(message,expected)]))

    def test_label_preparation_never_guesses_human_answers_or_overwrites(self):
        self.message('实验三截止10月23日。')
        path=self.root/'workbench.json'
        prepare_labels(self.database,path,limit=200)
        rows=json.loads(path.read_text(encoding='utf-8'))['labels']
        self.assertEqual(len(rows),1)
        self.assertFalse(rows[0]['reviewed'])
        self.assertEqual(rows[0]['expected_tasks'],[])
        self.assertIn('实验三',rows[0]['review_text'])
        self.assertEqual(evaluate(self.database,path)['matched'],0)
        with self.assertRaises(FileExistsError):prepare_labels(self.database,path,limit=200)

    def test_legacy_labels_and_model_degradation_are_reported(self):
        external=dict(platform='chaoxing-web',kind='course_notice',message_id='notice_1',title='实验三',notice_body='请提交报告，截止10月23日。')
        message=self.message('实验三：请提交报告，截止10月23日。',external=external)
        key=hashlib.sha256(b'notice_1').hexdigest()[:16]
        labels=self.labels([dict(key=key,task=True,deadline='2026-10-23',operation='create')],schema=1)
        def degraded(message):
            return dict(candidates=[dict(title='实验三',deadline='2026-10-23',operation='create')],limited=True,trace=[dict(tool='model_assist',status='fallback')])
        result=evaluate(self.database,labels,runner=degraded,mode='qwen',model='test-only')
        self.assertEqual(result['counts'],dict(tp=1,fp=0,fn=0))
        self.assertEqual(result['limited'],1)
        self.assertFalse(result['target_evidence_complete'])

    def test_cloud_or_non_loopback_model_endpoint_is_rejected(self):
        for value in ('https://example.com','http://192.168.1.2:11434','http://localhost.example.com:11434','http://user:pass@localhost:11434'):
            with self.subTest(value=value),self.assertRaises(ValidationError):local_provider(value,'qwen3:4b')
        self.assertEqual(local_provider('http://127.0.0.1:11434','qwen3:4b').kind,'ollama')

    def test_model_without_proposal_does_not_reintroduce_rejected_narrative_tasks(self):
        class QuietProvider:
            def chat(self,messages,tools):return dict(content='没有补充任务。')
        external=dict(kind='course_notice',title='课程通知',notice_body='请查收附件。',attachments=[dict(name='说明.txt',status='extracted',text='研究人员发表了论文。')])
        message=dict(text='课程通知\n请查收附件。\n研究人员发表了论文。',captured_at='2026-10-20T12:00:00+08:00',course='数据库',scope='一班',external=external)
        self.assertEqual(model_runner(self.box,QuietProvider())(message)['candidates'],[])

    def test_missing_database_is_not_created(self):
        path=self.root/'does-not-exist.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):evaluate(path,self.labels([]))
        self.assertFalse(path.exists())

    def test_cli_runs_without_source_text_and_protects_input_files(self):
        message=self.message('实验三截止10月23日。')
        labels=self.labels([self.row(message,[dict(title='实验三',deadline='2026-10-23',operation='create')])])
        script=Path(__file__).resolve().parents[1]/'scripts/evaluate-recognition.py'
        args=[sys.executable,'-B',str(script),'--database',str(self.database),'--labels',str(labels)]
        report=self.root/'report.json'
        environment=dict(os.environ,PYTHONIOENCODING='utf-8')
        result=subprocess.run(args+['--output',str(report)],capture_output=True,encoding='utf-8',timeout=10,env=environment)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['deadline_exact'],1)
        self.assertNotIn('实验三',result.stdout)
        for path in (labels,self.database):
            before=path.read_bytes()
            result=subprocess.run(args+['--output',str(path)],capture_output=True,encoding='utf-8',timeout=10,env=environment)
            self.assertEqual(result.returncode,2)
            self.assertEqual(path.read_bytes(),before)


if __name__ == '__main__':unittest.main()
