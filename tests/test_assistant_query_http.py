import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from courseinbox.agent import Agent
from courseinbox.core import Inbox
from courseinbox.http import create_server


class AssistantQueryHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.inbox=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.token='isolated-assistant-query-http-token'
        for text,scope in [('《C语言程序设计》实验一，2026年10月24日18:00提交PDF报告。','一班'),
                           ('《C语言程序设计》实验二，2026年10月24日18:00提交PDF报告。','二班')]:
            created=self.inbox.ingest(text,captured_at='2026-10-23T12:00:00+08:00',scope=scope)
            self.inbox.confirm(created['proposals'][0]['id'])
        self.server=create_server('127.0.0.1',0,self.inbox,self.token,agent=Agent(self.inbox),reminder_port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}/api/assistant'
        self.clock=patch('courseinbox.agent.now_iso',return_value='2026-10-23T19:00:00+08:00');self.clock.start()

    def tearDown(self):
        self.clock.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def ask(self,question,course='',scope=None):
        request=urllib.request.Request(self.url,data=json.dumps(dict(question=question,course=course,scope=scope)).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:return error.code,json.loads(error.read())

    def state(self):
        with self.inbox.connection() as db:
            return {name:[tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in ('messages','tasks','proposals','sources','history')}

    def test_real_http_combines_course_week_and_class_without_writes(self):
        before=self.state()
        status,result=self.ask('C语言明天有哪些未提交任务',scope='一班')
        self.assertEqual(status,200);self.assertIn('/ 实验一：',result['answer']);self.assertNotIn('/ 实验二：',result['answer'])
        self.assertEqual(self.state(),before)

    def test_invalid_date_is_a_clear_http_error(self):
        status,result=self.ask('2月30日有哪些任务')
        self.assertEqual(status,400);self.assertIn('日期',result['error'])

    def test_first_person_query_keeps_class_scope_and_does_not_write(self):
        before=self.state()
        status,result=self.ask('我明天有哪些任务未提交？',scope='一班')
        self.assertEqual(status,200)
        self.assertIn('/ 实验一：',result['answer'])
        self.assertNotIn('/ 实验二：',result['answer'])
        self.assertEqual(self.state(),before)

    def test_explicit_course_cannot_widen_server_scope(self):
        status,result=self.ask('课程：其他课程，有哪些任务',course='C语言程序设计',scope='一班')
        self.assertEqual(status,200);self.assertNotIn('• ',result['answer'])
