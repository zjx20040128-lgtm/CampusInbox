import json
import io
import zipfile
import base64
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox
from courseinbox.chaoxing import ingest_web_message
from courseinbox.http import create_server

TOKEN = 'test-main-token-never-use-in-production'
ORIGIN = 'chrome-extension://' + 'a' * 32
PAYLOAD = dict(message_id='1604819152831253728', text='明天18:00前提交实验报告。',
               conversation='课程讨论', sender='测试同学', display_time='昨天 23:57',
               captured_at='2026-10-05T23:57:00+08:00', direction='received')


class ChaoxingApiTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('courseinbox.core.now_iso', return_value='2026-10-09T12:00:00+08:00')
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox = Inbox(Path(self.tmp.name) / 'db.sqlite3')
        self.server = create_server('127.0.0.1', 0, self.inbox, TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, body=None, token=TOKEN, origin=None):
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
        if origin: headers['Origin'] = origin
        req = urllib.request.Request(self.url + path, None if body is None else json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def pair(self):
        status, body = self.request('/api/chaoxing/pairing')
        self.assertEqual(status, 200)
        self.assertNotEqual(body['token'], TOKEN)
        return body['token']

    def test_real_text_metadata_and_stable_id_replay(self):
        token = self.pair()
        status, result = self.request('/api/chaoxing/messages', PAYLOAD, token, ORIGIN)
        self.assertEqual(status, 201)
        self.assertEqual(result, {'accepted': True, 'duplicate': False})
        stored = self.inbox.messages()[0]
        self.assertEqual(stored['text'], PAYLOAD['text'])
        self.assertFalse(stored['sample'])
        self.assertEqual(stored['external']['sender'], PAYLOAD['sender'])
        replay = dict(PAYLOAD, captured_at='2026-10-06T23:57:00+08:00', conversation='改名的会话')
        status, duplicate = self.request('/api/chaoxing/messages', replay, token, ORIGIN)
        self.assertEqual(status, 200)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate, {'accepted': True, 'duplicate': True})
        self.assertEqual(self.inbox.messages()[0]['id'], stored['id'])
        status, _ = self.request('/api/chaoxing/messages', dict(PAYLOAD, message_id='1604819152831253729'), token)
        self.assertEqual(status, 201)
        self.assertEqual(len(self.inbox.messages()), 2)
        settings_status,settings=self.request('/api/settings')
        self.assertEqual(settings_status,200)
        self.assertEqual(settings['chaoxing_web']['received_count'],2)
        self.assertEqual(settings['chaoxing_web']['chat_count'],2)

    def test_scoped_token_cannot_read_or_write_other_routes(self):
        token = self.pair()
        for path, body in [('/api/state', None), ('/api/chaoxing/pairing', None), ('/api/messages', {'text': 'test'})]:
            self.assertEqual(self.request(path, body, token)[0], 401)
        self.assertEqual(self.request('/api/chaoxing/messages', PAYLOAD, TOKEN)[0], 401)
        self.assertEqual(self.request('/api/chaoxing/messages', PAYLOAD, token, 'https://evil.example')[0], 403)
        self.assertEqual(self.request('/api/state', token=TOKEN, origin=ORIGIN)[0], 403)
        from unittest.mock import patch
        with patch('courseinbox.http.ipaddress.ip_address') as address:
            address.return_value.is_loopback = False
            self.assertEqual(self.request('/api/chaoxing/messages', token=token)[0], 403)

    def test_unknown_timestamp_is_preserved_and_has_no_deadline_draft(self):
        token = self.pair()
        status, result = self.request('/api/chaoxing/messages', dict(PAYLOAD, captured_at=None, display_time='刚刚'), token)
        self.assertEqual(status, 201)
        stored = self.inbox.messages()[0]
        self.assertFalse(stored['external']['time_known'])
        self.assertEqual(stored['external']['display_time'], '刚刚')
        self.assertEqual(self.inbox.proposals(), [])

    def test_unknown_time_reanalysis_cannot_invent_relative_deadline(self):
        payload = dict(PAYLOAD, captured_at=None, text='《时间未知课》 第一次作业，明天18:00前提交实验报告。')
        self.assertEqual(self.request('/api/chaoxing/messages', payload, self.pair())[0], 201)
        stored = self.inbox.messages()[0]
        self.assertEqual(self.request('/api/messages/' + stored['id'] + '/reanalyze', {})[0], 400)
        self.assertEqual(self.inbox.proposals(), [])

    def test_extraction_failure_preserves_body_and_next_message_is_accepted(self):
        text = '第一次作业，提交' + '、'.join('a' + str(i) for i in range(31)) + '。'
        token = self.pair()
        self.assertEqual(self.request('/api/chaoxing/messages', dict(PAYLOAD, text=text), token)[0], 201)
        stored = self.inbox.messages()[0]
        self.assertEqual(stored['text'], text)
        self.assertIn('extraction_warning', stored['external'])
        self.assertEqual(self.inbox.proposals(), [])
        self.assertEqual(self.request('/api/chaoxing/messages', dict(PAYLOAD, message_id='next-message'), token)[0], 201)

    def test_invalid_payloads_do_not_store_private_fields_or_empty_body(self):
        token = self.pair()
        for changes in [{'text': ''}, {'message_id': ''}, {'message_id': 'x' * 201}, {'cookie': 'private'},
                        {'captured_at': '昨天'}, {'direction': 'anything'}, {'text': 'x' * 30001}]:
            self.assertEqual(self.request('/api/chaoxing/messages', dict(PAYLOAD, **changes), token)[0], 400)
        self.assertEqual(self.inbox.messages(), [])

    def notice(self,**changes):
        return dict(message_id='fixture-notice-1',kind='course_notice',title='《软件工程高级管理技术》第二次课课前阅读',text='请提前阅读材料，做好研讨准备。请在明天上课前完成。具体要求请见附件。',course='软件工程高级管理技术',sender='示例老师',display_time='10-08(星期四) 12:06',captured_at='2026-10-08T12:06:00+08:00',url='https://notice.chaoxing.com/pc/notice/$CACG$fixture-1/detail',attachments=[dict(name='课前阅读说明.docx',url='https://d0.cldisk.com/download/'+'a'*32,status='extracted',text='请提交讨论提纲。')],**changes)
    def test_course_notice_preserves_body_attachments_and_creates_only_draft(self):
        payload=self.notice();token=self.pair()
        self.assertEqual(self.request('/api/chaoxing/messages',payload,token,ORIGIN)[0],201)
        stored=self.inbox.messages()[0]
        self.assertEqual(stored['source'],'学习通网页 · 课程通知')
        self.assertEqual(stored['course'],payload['course'])
        self.assertEqual(stored['external']['notice_body'],payload['text'])
        self.assertIn('请提交讨论提纲。',stored['text'])
        self.assertEqual(stored['external']['attachments'][0]['status'],'extracted')
        self.assertEqual(len(self.inbox.proposals()),1)
        self.assertEqual(self.inbox.tasks(),[])
        self.assertEqual(self.request('/api/chaoxing/messages',payload,token,ORIGIN)[1],dict(accepted=True,duplicate=True))
    def test_instruction_attachment_adds_reading_scope_without_false_missing_warning(self):
        payload=self.notice();payload['attachments'][0]['text']='一份可查证真实提交记录的实证研究、一份随机对照实验。\n每组内部分配，一个人只读一篇即可。三份材料都不要求通读，只读下表列出的页。\n材料 | 性质 | 只读这几页 | 页数\n报告甲 | 调查 | 第7、9页 | 2'
        self.assertEqual(self.request('/api/chaoxing/messages',payload,self.pair())[0],201)
        candidate=self.inbox.proposals()[0]['candidate']
        self.assertIn('每人只读一篇', ' '.join(candidate['requirements']))
        self.assertIn('报告甲：第7、9页',candidate['requirements'])
        self.assertFalse(any('附件正文尚未导入' in warning for warning in candidate['warnings']))
        self.assertEqual(candidate['title'],'第二次课课前阅读')
        self.assertFalse(any('实证研究' in item or '随机对照实验' in item for item in candidate['requirements']))
    def test_notice_unknown_time_and_attachment_failures_are_visible(self):
        payload=self.notice();payload['captured_at']=None;payload['attachments'][0].update(status='failed',text='',error='无法读取')
        self.assertEqual(self.request('/api/chaoxing/messages',payload,self.pair())[0],201)
        stored=self.inbox.messages()[0]
        self.assertFalse(stored['external']['time_known'])
        self.assertEqual(stored['external']['attachments'][0]['error'],'无法读取')
        self.assertEqual(self.inbox.proposals(),[])

    def test_title_only_notice_preserves_empty_original_body(self):
        payload=self.notice();payload.update(title='普通通知',text='',attachments=[])
        self.assertEqual(self.request('/api/chaoxing/messages',payload,self.pair())[0],201)
        stored=self.inbox.messages()[0]
        self.assertEqual(stored['external']['notice_body'],'')
        self.assertEqual(stored['external']['notice_body_state'],'empty')
        self.assertEqual(stored['text'].strip(),'普通通知')
        self.assertEqual(self.inbox.proposals(),[])
        self.assertEqual(self.inbox.tasks(),[])
    def test_attachment_retry_enriches_only_same_notice_without_creating_tasks(self):
        payload=self.notice();token=self.pair();payload['attachments'][0].update(status='failed',text='',error='网络失败')
        self.assertEqual(self.request('/api/chaoxing/messages',payload,token)[0],201)
        original=self.inbox.messages()[0]
        payload['attachments'][0].update(status='extracted',text='每人只读一篇。',error='')
        self.assertEqual(self.request('/api/chaoxing/messages',payload,token)[0],200)
        stored=self.inbox.messages()[0]
        self.assertEqual(stored['id'],original['id']);self.assertEqual(len(self.inbox.messages()),1)
        self.assertEqual(stored['external']['attachments'][0]['status'],'extracted')
        self.assertIn('每人只读一篇',stored['text']);self.assertEqual(len(self.inbox.proposals()),1);self.assertEqual(self.inbox.tasks(),[])
        payload['text']='修改的正文';payload['attachments'][0]['text']='不能替换原文'
        self.request('/api/chaoxing/messages',payload,token)
        self.assertEqual(self.inbox.messages()[0],stored)

    def test_attachment_enrichment_never_changes_confirmed_task(self):
        payload=self.notice();token=self.pair();payload['attachments'][0].update(status='partial',text='每人只读一篇。')
        self.request('/api/chaoxing/messages',payload,token)
        proposal=self.inbox.proposals()[0]
        self.assertEqual(self.request('/api/proposals/'+proposal['id']+'/confirm',{})[0],200)
        tasks=self.inbox.tasks()
        payload['attachments'][0].update(status='extracted',text='每人只读一篇。\n材料 | 性质 | 只读这几页 | 页数\n报告甲 | 调查 | 第7、9页 | 2')
        self.assertEqual(self.request('/api/chaoxing/messages',payload,token)[0],200)
        self.assertEqual(self.inbox.tasks(),tasks)
        self.assertEqual(len(self.inbox.proposals()),1)
        self.assertIn('报告甲：第7、9页',self.inbox.proposals()[0]['candidate']['requirements'])

    def test_notice_and_chat_ids_cannot_collide(self):
        token=self.pair();notice=self.notice();chat=dict(PAYLOAD,message_id=notice['message_id'])
        self.assertEqual(self.request('/api/chaoxing/messages',chat,token)[0],201)
        self.assertEqual(self.request('/api/chaoxing/messages',notice,token)[0],201)
        self.assertEqual(len(self.inbox.messages()),2)

    def test_structured_task_center_item_creates_rich_reviewable_draft(self):
        token=self.pair()
        payload=dict(
            kind='task_center',message_id='task_work_42',title='数据库实验三',text='完成实验并上传报告。',description='完成实验并上传报告。',
            course='数据库系统',conversation='数据库系统 · 计科1班',sender='王老师',display_time='10-09 20:00',
            captured_at='2026-10-09T20:00:00+08:00',direction='received',task_type='experiment',
            deadline='2026-10-13T23:59:00+08:00',submission_method='学习通上传',platform_status='未提交',
            teacher='王老师',url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&workId=42',
            field_evidence={'title':'数据库实验三','deadline':'截止：10月13日 23:59','submission_method':'学习通上传'})
        status,result=self.request('/api/chaoxing/messages',payload,token,ORIGIN)
        self.assertEqual(status,201)
        self.assertTrue(result['accepted'])
        self.assertEqual(self.inbox.messages()[0]['source'],'学习通网页 · 作业考试中心')
        self.assertEqual(len(self.inbox.proposals()),1)
        candidate=self.inbox.proposals()[0]['candidate']
        self.assertEqual(candidate['kind'],'experiment')
        self.assertEqual(candidate['deadline'],'2026-10-13T23:59:00+08:00')
        self.assertEqual(candidate['submission_method'],'学习通上传')
        self.assertEqual(candidate['teacher'],'王老师')
        self.assertEqual(candidate['platform_status'],'未提交')
        self.assertEqual(candidate['confidence'],'high')
        self.assertEqual(candidate['source_url'],payload['url'])
        self.assertEqual(self.inbox.tasks(),[])
        settings_status,settings=self.request('/api/settings')
        self.assertEqual(settings_status,200)
        self.assertEqual(settings['chaoxing_web']['received_count'],1)
        self.assertEqual(settings['chaoxing_web']['task_center_count'],1)
        task=self.inbox.confirm(self.inbox.proposals()[0]['id'])
        self.assertEqual(task['status'],'pending','platform status is evidence and must not mark the local task submitted')
        unsafe=dict(payload,message_id='task_work_unsafe',url='https://evil.example/work/42')
        self.assertEqual(self.request('/api/chaoxing/messages',unsafe,token,ORIGIN)[0],400)
    def test_structured_task_center_preserves_date_only_deadline(self):
        payload=dict(kind='task_center',message_id='task_exam_date_only',title='期末考试',text='考试安排',course='数据库系统',conversation='数据库系统 · 计科1班',sender='王老师',display_time='',captured_at='2026-10-09T20:00:00+08:00',direction='received',task_type='exam',deadline='2026-12-20',submission_method='',platform_status='未开始',teacher='王老师',url='https://mooc1.chaoxing.com/exam-ans/exam/test?id=9',field_evidence={'deadline':'2026-12-20'})
        status,_=self.request('/api/chaoxing/messages',payload,self.pair(),ORIGIN)
        self.assertEqual(status,201)
        candidate=self.inbox.proposals()[0]['candidate']
        self.assertEqual(candidate['deadline'],'2026-12-20')
        self.assertEqual(candidate['date_precision'],'date')
        self.assertEqual(candidate['requirements'],[])
    def test_notice_rejects_unsafe_links_and_unbounded_attachment_text(self):
        token=self.pair()
        for changes in [dict(url='https://evil.example/detail'),dict(attachments=[dict(name='bad.docx',url='javascript:alert(1)',status='listed')]),dict(attachments=[dict(name='big.docx',url='',status='extracted',text='a'*20001)])]:
            payload=self.notice();payload.update(changes)
            self.assertEqual(self.request('/api/chaoxing/messages',payload,token)[0],400)
        self.assertEqual(self.inbox.messages(),[])
    def test_scoped_attachment_extraction_accepts_only_documents(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>准备讨论提纲</w:t></w:r></w:p></w:body></w:document>')
        payload=dict(filename='课前说明.docx',content_base64=base64.b64encode(data.getvalue()).decode())
        token=self.pair();status,result=self.request('/api/chaoxing/attachments/extract',payload,token,ORIGIN)
        self.assertEqual(status,200);self.assertEqual(result['text'],'准备讨论提纲')
        self.assertEqual(self.request('/api/chaoxing/attachments/extract',dict(payload,filename='program.exe'),token,ORIGIN)[0],400)
        self.assertEqual(self.request('/api/chaoxing/attachments/extract',payload,TOKEN,ORIGIN)[0],401)
        self.assertEqual(self.request('/api/state',token=token)[0],401)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows duplicate-bind regression')
    def test_windows_repeated_start_cannot_run_two_servers_on_same_port(self):
        second = None
        try:
            with self.assertRaises(OSError):
                second = create_server('127.0.0.1', self.server.server_port, self.inbox, TOKEN)
        finally:
            if second is not None: second.server_close()


class ChaoxingHistoricalIntakeTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('courseinbox.core.now_iso', return_value='2026-10-16T17:05:00+08:00')
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox = Inbox(Path(self.tmp.name) / 'history.sqlite3')

    def task(self, **changes):
        body = dict(kind='task_center', message_id='history-task', title='数据库实验三', text='完成实验并上传报告。',
                    course='数据库系统', conversation='数据库系统 · 计科1班', sender='王老师',
                    captured_at='2026-09-15T12:00:00+08:00', task_type='experiment',
                    deadline='2026-09-15T23:59:00+08:00', platform_status='未提交',
                    url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&workId=42',
                    field_evidence={'deadline': '截止：2026-09-15 23:59'})
        body.update(changes)
        return body

    def notice(self, text, **changes):
        body = dict(kind='course_notice', message_id='history-notice', title='第一次作业', text=text,
                    course='数据库系统', conversation='数据库系统 · 计科1班', sender='王老师',
                    captured_at='2026-09-15T12:00:00+08:00',
                    url='https://notice.chaoxing.com/pc/notice/history-notice/detail', attachments=[])
        body.update(changes)
        return body

    def test_expired_automatic_task_keeps_source_without_pending_review(self):
        payload = self.task()
        result = ingest_web_message(self.inbox, payload)
        self.assertFalse(result['duplicate'])
        self.assertEqual(self.inbox.proposals(), [])
        stored = self.inbox.messages()[0]
        self.assertEqual(stored['text'], payload['text'])
        self.assertEqual(stored['captured_at'], payload['captured_at'])
        self.assertEqual(stored['received_at'], '2026-10-16T17:05:00+08:00')
        self.assertEqual(stored['external']['deadline'], payload['deadline'])
        self.assertEqual(self.inbox.proposals(status='archived')[0]['candidate']['title'], payload['title'])
        self.assertEqual(self.inbox.tasks(), [])
        ingest_web_message(self.inbox, payload)
        self.assertEqual(len(self.inbox.messages()), 1)
        self.assertEqual(len(self.inbox.proposals(status='archived')), 1)

    def test_published_long_ago_with_future_or_unknown_deadline_stays_reviewable(self):
        ingest_web_message(self.inbox, self.task(deadline='2026-10-30', field_evidence={'deadline': '2026-10-30'}))
        ingest_web_message(self.inbox, self.notice('请完成并提交第一份实验报告。'))
        self.assertEqual(len(self.inbox.proposals()), 2)

    def test_date_in_task_name_or_publication_is_not_a_deadline(self):
        ingest_web_message(self.inbox, self.notice('任务名称：作业20260915\n发布时间：2026-09-15\n请提交实验报告。', title='作业20260915'))
        candidate = self.inbox.proposals()[0]['candidate']
        self.assertIsNone(candidate['deadline'])
        self.assertEqual(candidate['date_precision'], 'unknown')

    def test_explicit_deadline_after_publication_date_wins(self):
        ingest_web_message(self.inbox, self.notice('任务名称：实验报告，发布时间：2026-09-15，截止2026-10-30，请提交报告。'))
        self.assertEqual(self.inbox.proposals()[0]['candidate']['deadline'], '2026-10-30')

    def test_ended_or_submitted_platform_status_archives_without_guessing_local_status(self):
        for index, status in enumerate(('已结束', '已提交')):
            ingest_web_message(self.inbox, self.task(message_id='ended-' + str(index), deadline=None, field_evidence={}, platform_status=status,
                               url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&workId=' + str(42 + index)))
        self.assertEqual(self.inbox.proposals(), [])
        self.assertEqual(len(self.inbox.proposals(status='archived')), 2)
        self.assertEqual(self.inbox.tasks(), [])

    def test_expired_notice_and_chat_are_archived(self):
        ingest_web_message(self.inbox, self.notice('请完成第一次作业，截止2026-09-15。'))
        ingest_web_message(self.inbox, dict(message_id='history-chat', text='第二次作业请于2026-09-15前提交实验报告。',
                           conversation='数据库系统', captured_at='2026-09-15T12:00:00+08:00'))
        self.assertEqual(self.inbox.proposals(), [])
        self.assertEqual(len(self.inbox.proposals(status='archived')), 2)

    def test_end_notice_with_semicolon_has_no_new_pending_task(self):
        ingest_web_message(self.inbox, self.notice('任务结束提醒；作业已结束；请查看实验报告结果。'))
        self.assertEqual(self.inbox.proposals(), [])
        self.assertEqual(len(self.inbox.proposals(status='archived')), 1)

    def test_expired_manual_import_and_explicit_deadline_change_stay_reviewable(self):
        self.inbox.ingest('第一次作业，截止2026-09-15。', captured_at='2026-09-15T12:00:00+08:00')
        ingest_web_message(self.inbox, self.notice('任务名称：第二次作业，原截止2026-09-15，现延期到2026-10-30。'))
        self.assertEqual(len(self.inbox.proposals()), 2)
        revised = next(p for p in self.inbox.proposals() if p['candidate']['operation'] == 'update')
        self.assertEqual(revised['candidate']['deadline'], '2026-10-30')

    def test_current_date_only_deadline_survives_the_entire_beijing_day(self):
        ingest_web_message(self.inbox, self.task(deadline='2026-10-16', field_evidence={'deadline': '2026-10-16'}))
        self.assertEqual(len(self.inbox.proposals()), 1)

    def test_reopening_archives_only_legacy_unconfirmed_history_and_keeps_evidence(self):
        with patch('courseinbox.intake_policy.archive_reason', return_value=''):
            result = ingest_web_message(self.inbox, self.task())
        original = self.inbox.messages()[0]
        proposal_id = result['proposals'][0]['id']
        reopened = Inbox(self.inbox.path)
        self.assertEqual(reopened.proposals(), [])
        self.assertEqual(reopened.proposals(status='archived')[0]['id'], proposal_id)
        self.assertEqual(reopened.messages()[0], original)
        self.assertEqual(Inbox(self.inbox.path).proposals(status='archived')[0]['id'], proposal_id)
        self.assertEqual(len(reopened.proposals(status=None)), 1)

    def test_reopening_keeps_draft_that_was_valid_when_first_received(self):
        with patch('courseinbox.core.now_iso', return_value='2026-09-14T12:00:00+08:00'):
            ingest_web_message(self.inbox, self.task(captured_at='2026-09-01T12:00:00+08:00'))
        original = self.inbox.proposals()[0]
        reopened = Inbox(self.inbox.path)
        self.assertEqual(len(reopened.proposals()), 1)
        self.assertEqual(reopened.proposals()[0]['id'], original['id'])
        self.assertEqual(reopened.proposals(status='archived'), [])

    def test_explicit_reanalysis_can_restore_history_and_survives_reopening(self):
        result = ingest_web_message(self.inbox, self.notice('第一次作业，截止2026-09-15，请提交报告。'))
        message_id = result['message']['id']
        self.assertEqual(self.inbox.proposals(), [])
        self.inbox.reanalyze(message_id)
        restored = self.inbox.proposals()[0]
        self.assertEqual(restored['candidate']['deadline'], '2026-09-15')
        reopened = Inbox(self.inbox.path)
        self.assertEqual(reopened.proposals()[0]['id'], restored['id'])
        self.assertEqual(reopened.messages()[0]['text'], result['message']['text'])

    def test_reopening_preserves_confirmed_tasks_and_pending_evidence_for_existing_task(self):
        with patch('courseinbox.intake_policy.archive_reason', return_value=''):
            result = ingest_web_message(self.inbox, self.task())
        task = self.inbox.confirm(result['proposals'][0]['id'])
        updated = ingest_web_message(self.inbox, self.task(message_id='same-task-new-evidence', platform_status='已结束',
                                     deadline='2026-09-16T23:59:00+08:00', field_evidence={'deadline': '截止：2026-09-16 23:59'}))
        self.assertEqual(updated['proposals'][0]['target_id'], task['id'])
        self.assertEqual(updated['proposals'][0]['status'], 'pending')
        reopened = Inbox(self.inbox.path)
        reopened_task = reopened.tasks()[0]
        reopened_task.pop('platform_check', None)
        self.assertEqual(reopened_task, task)
        self.assertEqual(len(reopened.proposals()), 1)
        self.assertEqual(reopened.proposals(status='archived'), [])

    def test_attachment_retry_does_not_rearchive_explicitly_restored_history(self):
        payload = self.notice('第一次作业，截止2026-09-15，请提交报告。', attachments=[
            dict(name='要求.docx', url='', status='failed', text='', error='暂时读取失败')])
        result = ingest_web_message(self.inbox, payload)
        self.inbox.reanalyze(result['message']['id'])
        self.assertEqual(len(self.inbox.proposals()), 1)
        payload['attachments'][0].update(status='extracted', text='请提交报告总结。', error='')
        enriched = ingest_web_message(self.inbox, payload)
        self.assertTrue(enriched['enriched'])
        self.assertEqual(len(self.inbox.proposals()), 1)
        self.assertEqual(self.inbox.messages()[0]['external']['attachments'][0]['status'], 'extracted')

    def test_attachment_retry_keeps_draft_that_was_valid_at_first_receipt(self):
        payload = self.notice('第一次作业，截止2026-09-15，请提交报告。',
                              captured_at='2026-09-01T12:00:00+08:00', attachments=[
                                  dict(name='要求.docx', url='', status='failed', text='', error='暂时读取失败')])
        with patch('courseinbox.core.now_iso', return_value='2026-09-14T12:00:00+08:00'):
            ingest_web_message(self.inbox, payload)
        self.assertEqual(len(self.inbox.proposals()), 1)
        payload['attachments'][0].update(status='extracted', text='请提交报告总结。', error='')
        self.assertTrue(ingest_web_message(self.inbox, payload)['enriched'])
        self.assertEqual(len(self.inbox.proposals()), 1)

    def test_automatic_chat_keeps_partial_completion_and_group_submission_conditions(self):
        for index, text in enumerate((
                '《数学》第一次作业已完成一半，请于2026年10月30日提交实验报告。',
                '《数学》第一次作业已完成的同学请忽略，未完成的同学请于2026年10月30日提交报告。',
                '《数学》第一次作业已提交的同学请忽略，其余同学请于2026年10月30日提交报告。',
                '《数学》第一次作业已提交第一部分，请于2026年10月30日提交其余报告。')):
            with self.subTest(text=text):
                result = ingest_web_message(self.inbox, dict(message_id='partial-chat-' + str(index), text=text,
                                           conversation='数学课', captured_at='2026-10-15T12:00:00+08:00'))
                self.assertEqual(result['proposals'][0]['status'], 'pending')
                self.assertEqual(result['proposals'][0]['candidate']['deadline'], '2026-10-30')
        self.assertEqual(len(self.inbox.proposals()), 4)
        self.assertEqual(self.inbox.proposals(status='archived'), [])
