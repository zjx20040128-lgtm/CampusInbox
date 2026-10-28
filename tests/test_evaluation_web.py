import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox
from courseinbox.evaluation import prepare_labels
from courseinbox.http import create_server


class WebEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.box=Inbox(self.root/'data/inbox.sqlite3')
        self.box.ingest('实验三，请提交报告，截止10月25日。',course='数据库',captured_at='2026-10-21T09:00:00+08:00',candidates=[])
        directory=self.root/'data/verification';directory.mkdir()
        prepare_labels(self.box.path,directory/'workbench.json')
        self.token='web-evaluation-main-token-only'
        self.server=create_server('127.0.0.1',0,self.box,self.token,root=self.root,reminder_port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,path,body=None,auth=True,origin=None):
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer '+self.token
        if origin:headers['Origin']=origin
        request=urllib.request.Request(self.base+'/api/evaluation/'+path,headers=headers,data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:return error.code,json.loads(error.read())

    def labels(self):return self.request('labels?dataset=workbench.json')[1]

    def review(self):
        page=self.labels()
        return self.request('labels',dict(dataset='workbench.json',key=page['items'][0]['key'],revision=page['revision'],reviewed=True,expected_tasks=[dict(title='实验三',deadline='2026-10-25',operation='create')]))

    def test_holdout_creation_and_default_run_never_include_development(self):
        for i in range(12):self.box.ingest(f'课程阅读{i}，请准备讨论。',candidates=[])
        code,result=self.request('datasets',dict(holdout=True))
        self.assertEqual(code,200)
        name=result['id'];path=self.root/'data/verification'/name
        value=json.loads(path.read_text(encoding='utf-8'))
        for row in value['labels']:
            row.update(reviewed=True,expected_tasks=[])
        path.write_text(json.dumps(value),encoding='utf-8')
        page=self.request('labels?dataset='+name)[1]
        self.assertIn('split',page['items'][0])
        code,job=self.request('runs',dict(dataset=name,mode='rules'))
        self.assertEqual(code,200)
        self.server.evaluation.thread.join(timeout=8)
        final=self.request('runs?id='+job['id'])[1]
        self.assertEqual(final['results'][0]['labeled'],result['holdout'])
        self.assertEqual(final['results'][0]['evaluation_split'],'holdout')

    def test_requires_main_token_and_rejects_cross_origin(self):
        self.assertEqual(self.request('datasets',auth=False)[0],401)
        self.assertEqual(self.request('datasets',origin='https://outside.invalid')[0],403)
        self.assertEqual(self.request('labels?dataset=../inbox.sqlite3')[0],400)
        self.assertEqual(self.request('report?id=../inbox.sqlite3')[0],400)

    def test_annotation_stays_unreviewed_until_explicit_save_and_version_is_checked(self):
        code,result=self.request('datasets');self.assertEqual(code,200)
        data=result['datasets'][0]
        self.assertEqual((data['total'],data['reviewed']),(1,0))
        page=self.labels();before=Path(self.box.path).read_bytes()
        self.assertIn('实验三',page['items'][0]['text'])
        self.assertEqual(page['items'][0]['expected_tasks'],[])
        self.assertEqual(self.review()[0],200)
        self.assertEqual(self.request('labels',dict(dataset='workbench.json',key=page['items'][0]['key'],revision=page['revision'],reviewed=True,expected_tasks=[]))[0],409)
        self.assertTrue(self.labels()['items'][0]['reviewed'])
        self.assertEqual(Path(self.box.path).read_bytes(),before)

    def test_invalid_task_answer_is_not_saved(self):
        page=self.labels()
        body=dict(dataset='workbench.json',key=page['items'][0]['key'],revision=page['revision'],reviewed=True,expected_tasks=[dict(title='实验三',deadline='2026-02-30',operation='create')])
        self.assertEqual(self.request('labels',body)[0],400)
        self.assertFalse(self.labels()['items'][0]['reviewed'])

    def test_label_view_shows_absolute_deadline_without_changing_raw_text_or_answers(self):
        text='测试作业；剩余48小时30分钟；未交'
        self.box.ingest(text,course='测试',captured_at='2026-10-21T09:00:00+08:00',candidates=[],external=dict(platform='chaoxing-web',message_id='evaluation_deadline_sample',url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42',kind='task_center',title='测试作业',deadline='2026-10-25T20:00:00+08:00'))
        path=self.root/'data/verification/countdown.json';prepare_labels(self.box.path,path)
        original=path.read_bytes()
        _,page=self.request('labels?dataset=countdown.json')
        item=next(item for item in page['items'] if item['text']==text)
        self.assertIn('2026-10-25 20:00',item['display_text'])
        self.assertNotIn('剩余48',item['display_text'])
        self.assertEqual(item['deadline_source'],'message')
        self.assertEqual(item['expected_tasks'],[])
        self.assertFalse(item['reviewed'])
        self.assertIsNone(item['published_at'])
        self.assertEqual(path.read_bytes(),original)

    def test_countdown_without_absolute_evidence_is_not_guessed(self):
        text='测试作业；剩余48小时30分钟；未交'
        self.box.ingest(text,course='测试',captured_at='2026-10-21T09:00:00+08:00',candidates=[],external=dict(platform='chaoxing-web',message_id='evaluation_deadline_sample',url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42',kind='task_center',title='测试作业'))
        prepare_labels(self.box.path,self.root/'data/verification/countdown.json')
        _,page=self.request('labels?dataset=countdown.json')
        item=next(item for item in page['items'] if item['text']==text)
        self.assertIn('截止未获取',item['display_text'])
        self.assertNotIn('剩余48',item['display_text'])
        self.assertIsNone(item['deadline'])

    def test_revision_describes_the_same_bytes_as_the_returned_answers(self):
        path=self.root/'data/verification/workbench.json'
        original=path.read_bytes();replacement=json.loads(original)
        replacement['labels'][0].update(reviewed=True,expected_tasks=[])
        changed=json.dumps(replacement).encode()
        read_bytes=Path.read_bytes
        def replace_after_read(target):
            content=read_bytes(target)
            if target==path:target.write_bytes(changed)
            return content
        with patch.object(Path,'read_bytes',replace_after_read):
            page=self.labels()
        self.assertFalse(page['items'][0]['reviewed'])
        self.assertEqual(page['revision'],hashlib.sha256(original).hexdigest())
        self.assertNotEqual(page['revision'],hashlib.sha256(changed).hexdigest())

    def test_preparation_and_pagination_are_bounded(self):
        (self.root/'data/verification/unrelated.json').write_text('[]',encoding='utf-8')
        self.assertEqual(self.request('datasets')[0],200)
        self.assertEqual(self.request('labels?dataset=unrelated.json')[0],400)
        self.assertEqual(self.request('datasets',dict(limit=201))[0],400)
        code,result=self.request('datasets',dict(limit=100))
        self.assertEqual(code,200)
        self.assertEqual(result['reviewed'],0)
        self.assertEqual(self.request('labels?dataset=workbench.json&limit=0')[0],400)
        self.assertEqual(self.request('labels?dataset=workbench.json&offset=-1')[0],400)

    def test_rule_job_uses_reviewed_labels_and_never_modifies_source_database(self):
        self.assertEqual(self.request('runs',dict(dataset='workbench.json',mode='rules'))[0],400)
        self.review()
        before=hashlib.sha256(Path(self.box.path).read_bytes()).hexdigest()
        code,job=self.request('runs',dict(dataset='workbench.json',mode='rules'))
        self.assertEqual(code,200)
        for _ in range(60):
            job=self.request('runs?id='+job['id'])[1]
            if job['state'] in ('completed','failed'):break
            time.sleep(.05)
        self.assertEqual(job['state'],'completed',job)
        report=self.request('report?id='+job['report_id'])[1]
        self.assertEqual(report['runs'][0]['task_precision'],1)
        self.assertNotIn('实验三',json.dumps(report,ensure_ascii=False))
        self.assertEqual(hashlib.sha256(Path(self.box.path).read_bytes()).hexdigest(),before)
        self.assertEqual(len(self.box.tasks()),0)
        self.assertEqual(len(self.request('reports')[1]['reports']),1)

    def test_model_unavailable_is_explained_and_never_downloaded(self):
        with patch('courseinbox.evaluation_web.ollama_data',side_effect=OSError()):
            self.assertFalse(self.request('models')[1]['available'])
            self.assertEqual(self.request('runs',dict(dataset='workbench.json',mode='compare',models=['qwen3:8b']))[0],400)

    def test_imported_reports_cannot_export_original_text_or_render_markup(self):
        directory=self.root/'data/evaluation';directory.mkdir()
        attack='<img src=x onerror=alert(1)>'
        report=dict(mode='rules',labeled=1,counts=dict(fp=attack,text='私人原文'),
                    latency_ms=dict(mean=12,text='私人原文'),cases=[dict(key='a'*24,status='evaluated',expected=attack,text='私人原文')],
                    loaded_model_snapshot=[dict(size=100,text='私人原文')])
        (directory/'imported.json').write_text(json.dumps(report),encoding='utf-8')
        code,value=self.request('report?id=saved--imported.json')
        self.assertEqual(code,200)
        self.assertNotIn('私人原文',json.dumps(value,ensure_ascii=False))
        self.assertNotIn('<img',json.dumps(value))

    def test_only_one_job_runs_and_cancel_does_not_create_a_completed_report(self):
        self.review();entered=threading.Event()
        from courseinbox.evaluation import EvaluationCancelled
        def delayed(*args,**kwargs):
            entered.set()
            for _ in range(100):
                if kwargs['cancel']():raise EvaluationCancelled()
                time.sleep(.01)
            self.fail('cancel was not observed')
        with patch('courseinbox.evaluation_web.evaluate',side_effect=delayed):
            code,job=self.request('runs',dict(dataset='workbench.json',mode='rules'))
            self.assertEqual(code,200);self.assertTrue(entered.wait(2))
            self.assertEqual(self.request('runs',dict(dataset='workbench.json',mode='rules'))[0],409)
            self.assertEqual(self.request('cancel',dict(id=job['id']))[0],200)
            for _ in range(60):
                status=self.request('runs?id='+job['id'])[1]
                if status['state']=='cancelled':break
                time.sleep(.02)
            self.assertEqual(status['state'],'cancelled')
            self.assertEqual(self.request('reports')[1]['reports'],[])


if __name__=='__main__':unittest.main()
