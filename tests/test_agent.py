import tempfile
import unittest
from pathlib import Path
from courseinbox.core import Inbox, ValidationError
from courseinbox.agent import Agent, AgentError

AT = '2026-10-03T16:00:00+08:00'
TEXT = '《软件工程》 第三次作业，截止10月12日23:59。'

def reply(calls=None, content=''):
    return {'role':'assistant','content':content,'tool_calls':calls or []}
def call(name,args,ident='1'):
    return {'id':ident,'type':'function','function':{'name':name,'arguments':args}}

class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []
    def chat(self, messages, tools):
        self.seen.append((messages.copy(),tools))
        return next(self.responses)

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.inbox = Inbox(Path(self.temp.name) / 'test.db')
    def tearDown(self):
        self.temp.cleanup()
    def test_offline_mode_explicitly_returns_rules_without_fake_trace(self):
        a = Agent(self.inbox)
        result = a.analyze(TEXT, AT, '', '1班')
        self.assertEqual(result['mode'], 'rules')
        self.assertEqual(result['trace'], [])
        self.assertEqual(result['candidates'][0]['deadline'],'2026-10-12T23:59:00+08:00')
    def test_model_proposes_draft_but_cannot_write_task(self):
        p = FakeProvider([reply([call('propose_task',{'title':'第三次作业','course':'软件工程','deadline':'2026-10-12T23:59:00+08:00','deadline_evidence':'10月12日23:59','evidence':TEXT})]),reply(content='草稿已生成')])
        result = Agent(self.inbox,p).analyze(TEXT,AT,'软件工程','1班')
        self.assertEqual(result['mode'],'agent')
        self.assertEqual(result['candidates'][0]['scope'],'1班')
        self.assertEqual(result['trace'][0]['tool'],'propose_task')
        self.assertEqual(self.inbox.tasks(),[])
        proposal_tool=next(tool for tool in p.seen[0][1] if tool['function']['name']=='propose_task')
        properties=proposal_tool['function']['parameters']['properties']
        self.assertIn('submission_method',properties)
        self.assertIn('presentation',properties['kind']['enum'])
        required=proposal_tool['function']['parameters']['required']
        self.assertIn('deadline_evidence',required)
        self.assertIn('submission_evidence',required)
        self.assertIn('submission_method',required)
    def test_tools_cannot_expand_class_scope(self):
        first = self.inbox.ingest(TEXT,captured_at=AT,scope='2班')
        self.inbox.confirm(first['proposals'][0]['id'])
        p = FakeProvider([reply([call('search_tasks',{'query':'','scope':'2班'})]),reply(content='没有任务')])
        a = Agent(self.inbox,p)
        result = a.ask('有什么任务',course='软件工程',scope='1班')
        self.assertEqual(result['trace'][0]['result']['count'],0)
        self.assertNotIn('scope',p.seen[0][1][0]['function']['parameters']['properties'])
    def test_unknown_and_write_tools_refused_in_question_mode(self):
        p = FakeProvider([reply([call('delete_task',{}),call('propose_task',{'title':'危险草稿'},'2')]),reply(content='没有修改')])
        result = Agent(self.inbox,p).ask('帮我删掉所有任务')
        self.assertEqual(len(result['trace']),2)
        self.assertTrue(all('error' in x['result'] for x in result['trace']))
        self.assertEqual(self.inbox.tasks(),[])
    def test_looping_model_stops_after_eight_calls(self):
        p = FakeProvider([reply([call('search_tasks',{'query':str(i)},str(i))]) for i in range(20)])
        result = Agent(self.inbox,p).ask('循环')
        self.assertEqual(len(result['trace']),8)
        self.assertTrue(result['limited'])
    def test_invented_evidence_or_scope_is_refused(self):
        args={'title':'第三次作业','course':'软件工程','scope':'2班','evidence':'老师说全班免交','deadline':'2026-10-12T23:59:00+08:00'}
        p = FakeProvider([reply([call('propose_task',args)]),reply(content='无法解析')])
        result=Agent(self.inbox,p).analyze(TEXT,AT,'软件工程','1班')
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['candidates'][0]['title'],'第三次作业')
        self.assertIn('error',result['trace'][0]['result'])
    def test_failure_is_visible_not_silently_claimed_as_agent_success(self):
        class Broken:
            def chat(self,*args):
                raise AgentError('模型不可达')
        result=Agent(self.inbox,Broken()).analyze(TEXT,AT,'','')
        self.assertEqual(result['candidates'][0]['title'],'第三次作业')
        self.assertIn('模型辅助暂不可用',result['answer'])
        self.assertEqual(result['trace'][0]['tool'],'model_assist')

if __name__ == '__main__':
    unittest.main()
