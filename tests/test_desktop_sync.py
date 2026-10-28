import base64,io,json,tempfile,unittest,urllib.request,urllib.error,threading
from pathlib import Path
from unittest.mock import patch
from courseinbox.core import Inbox
from courseinbox.desktop_sync import DesktopSync

class DesktopSyncTests(unittest.TestCase):
    def setUp(self):
        # Archive visibility is relative to the fixture's observation day.
        clock=patch('courseinbox.core.now_iso',return_value='2026-10-08T13:00:00+08:00');clock.start();self.addCleanup(clock.stop)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.inbox=Inbox(self.root/'db.sqlite3');self.sync=DesktopSync(self.inbox,Path(__file__).resolve().parents[1],autostart=False)
    def tearDown(self):self.sync.close();self.tmp.cleanup()
    def job(self):
        return dict(kind='course_notice',message_id='notice_fixture-desktop',title='《示例课程》课前阅读',course='示例课程',conversation='示例课程',sender='老师',display_time='10-08 12:06',captured_at='2026-10-08T12:06:00+08:00',direction='received',url='https://notice.chaoxing.com/pc/notice/$CACG$fixture-desktop/detail',text='请在明天上课前阅读材料。',attachments=[])
    def test_disabled_capture_does_not_ingest(self):
        self.sync.receive(dict(type='notice',job=self.job()));self.assertEqual(self.inbox.messages(),[])

    def test_initial_section_completion_cutoff_survives_restart_and_resets_on_logout(self):
        self.sync.enabled=True;key='a'*24
        self.sync.receive(dict(type='source',source='task_center',state='syncing',discovered_sections=[key]))
        first=self.sync.status()['sources']['task_center']['discovered_section_times'][key]
        self.sync.receive(dict(type='source',source='task_center',state='syncing',discovered_sections=[key]))
        self.assertEqual(self.sync.status()['sources']['task_center']['discovered_section_times'][key],first)
        other=DesktopSync(self.inbox,self.root,autostart=False);self.addCleanup(other.close)
        self.assertEqual(other.status()['sources']['task_center']['discovered_section_times'][key],first)
        self.sync.logout()
        self.assertEqual(self.sync.status()['sources']['task_center']['discovered_section_times'],{})
    def test_intake_is_persistent_deduplicated_and_draft_only(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='notice',job=self.job()));self.sync.receive(dict(type='notice',job=self.job()))
        self.assertEqual(len(self.inbox.messages()),1);self.assertEqual(len(self.inbox.proposals()),1);self.assertEqual(self.inbox.tasks(),[])
        self.assertEqual(self.inbox.proposals()[0]['candidate']['deadline'],'2026-10-09')
        self.assertEqual(self.sync.status()['queued'],0)
        self.assertIn('notice_fixture-desktop',self.sync.accepted)
    def chat(self, identity='chat-fixture-1', text='1'):
        return dict(kind='chat',message_id=identity,text=text,conversation='示例聊天',sender='老师',display_time='10-08 20:24',captured_at='2026-10-08T20:24:00+08:00',direction='received')
    def test_background_chat_preserves_short_messages_and_stable_replay(self):
        self.sync.enabled=True
        for job in [self.chat(),self.chat('chat-fixture-2','。'),self.chat()]:
            self.sync.receive(dict(type='chat',job=job))
        self.assertEqual(sorted(m['text'] for m in self.inbox.messages()),['1','。'])
        self.assertEqual(self.inbox.proposals(),[]);self.assertEqual(self.inbox.tasks(),[])
        self.assertEqual(self.sync.status()['queued'],0)
        self.assertIn('chat-fixture-1',self.sync.accepted)
    def test_background_chat_creates_reviewable_task_only(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='chat',job=self.chat(text='请在明天提交读书报告。')))
        self.assertEqual(len(self.inbox.messages()),1);self.assertEqual(len(self.inbox.proposals()),1)
        self.assertEqual(self.inbox.proposals()[0]['candidate']['deadline'],'2026-10-09')
        self.assertEqual(self.inbox.tasks(),[])
    def test_background_task_center_preserves_unknown_deadline_and_change_evidence(self):
        self.sync.enabled=True
        job=dict(kind='task_center',message_id='task_work_43_a',title='真实列表作业',text='真实列表作业；未交',description='',course='示例课程',conversation='示例课程',sender='',display_time='',captured_at='2026-10-11T12:00:00+08:00',direction='received',task_type='assignment',deadline=None,submission_method='',platform_status='未交',teacher='',url='https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&workId=43',field_evidence={'title':'真实列表作业'})
        self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(len(self.inbox.messages()),1)
        self.assertIsNone(self.inbox.proposals()[0]['candidate']['deadline'])
        self.assertEqual(self.inbox.tasks(),[])
        self.inbox.confirm(self.inbox.proposals()[0]['id'])
        changed=dict(job,message_id='task_work_43_b',deadline='2026-10-15',field_evidence={'title':'真实列表作业','deadline':'截止：2026-10-15'})
        self.sync.receive(dict(type='task_center',job=changed))
        self.assertEqual(len(self.inbox.messages()),2)
        self.assertEqual(len(self.inbox.proposals()),1)
        self.assertEqual(self.inbox.proposals()[0]['action'],'merge')
        self.inbox.confirm(self.inbox.proposals()[0]['id'])
        self.assertEqual(self.inbox.tasks()[0]['deadline'],'2026-10-15')
        extended=dict(changed,message_id='task_work_43_c',deadline='2026-10-16',field_evidence={'title':'真实列表作业','deadline':'截止：2026-10-16'})
        self.sync.receive(dict(type='task_center',job=extended))
        self.assertEqual(self.inbox.proposals()[0]['action'],'conflict')
        self.sync.receive(dict(type='source',source='task_center',state='partial',error='task_center',stage='task_list',pending_count=2,checked=True,issues=[{'course_index':5,'section':'assignment'},{'course_index':6,'section':'exam'},{'course_index':'secret','section':'course'}]))
        self.assertEqual(self.sync.status()['sources']['task_center']['pending_count'],2)
        self.assertEqual(self.sync.status()['sources']['task_center']['issue_summary'],'第5门课作业、第6门课考试')
    def test_task_center_scheduled_course_budget_is_not_reported_as_failure(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='status',state='connected'))
        self.sync.receive(dict(type='source',source='task_center',state='syncing',checked=True,pending_count=6,failed_count=0,issues=[]))
        status=self.sync.status()
        self.assertEqual(status['state'],'connected')
        self.assertEqual(status['sources']['task_center']['state'],'syncing')
        self.assertEqual(status['sources']['task_center']['pending_count'],6)
        self.assertIsNotNone(status['sources']['task_center']['last_checked'])
        self.assertIsNone(status['sources']['task_center']['last_success'])
    def test_chat_problem_remains_visible_when_notices_succeed(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='source',source='chat',state='retrying',error='chat',stage='chat_ready',reason='timeout'))
        self.sync.receive(dict(type='source',source='notice',state='connected',checked=True))
        self.sync.receive(dict(type='status',state='connected',checked=True))
        status=self.sync.status()
        self.assertEqual(status['state'],'partial');self.assertIn('聊天',status['last_error'])
        self.assertEqual(status['sources']['notice']['state'],'connected')
        self.assertEqual(status['sources']['chat']['state'],'retrying')
        self.sync.receive(dict(type='source',source='chat',state='syncing'))
        self.assertEqual(self.sync.status()['state'],'partial')
        self.assertIn('聊天',self.sync.status()['last_error'])
        self.sync.receive(dict(type='source',source='chat',state='connected',checked=True))
        self.assertEqual(self.sync.status()['state'],'connected')
        self.assertTrue(self.sync.status()['sources']['chat']['last_success'])
    def test_chat_failure_identifies_safe_conversation_ordinal(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='source',source='chat',state='partial',error='chat',stage='chat_content',issues=[{'conversation_index':2},{'conversation_index':'secret'}],pending_count=1,checked=True))
        self.assertEqual(self.sync.status()['sources']['chat']['issue_summary'],'第2个会话')
        self.assertNotIn('secret',json.dumps(self.sync.status()))
    def test_notice_gap_identifies_safe_list_ordinal(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='source',source='notice',state='partial',error='coverage',coverage='partial',issues=[{'notice_index':3},{'notice_index':'secret'}],media_pending_count=1,checked=True))
        status=self.sync.status()
        self.assertEqual(status['sources']['notice']['issue_summary'],'第3条通知')
        self.assertIn('原文核对',status['sources']['notice']['error']);self.assertNotIn('secret',json.dumps(status))
    def test_paused_and_stale_chat_workers_cannot_capture(self):
        self.sync.enabled=True;epoch=self.sync.epoch;self.sync.pause()
        self.sync.receive(dict(type='chat',job=self.chat()),epoch)
        self.sync.receive(dict(type='source',source='chat',state='connected',checked=True),epoch)
        self.assertEqual(self.sync.status()['state'],'paused');self.assertEqual(self.inbox.messages(),[])

    def test_status_never_exposes_profile_or_auth_values(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='status',state='expired',error='https://passport2.chaoxing.com/?cookie=secret',cookie='secret'))
        self.assertNotIn('secret',json.dumps(self.sync.status()));self.assertNotIn('profile',self.sync.status());self.assertEqual(self.sync.status()['state'],'expired')
    def test_paused_session_configuration_survives_reload(self):
        self.sync.enabled=True;self.sync.pause();other=DesktopSync(self.inbox,Path(__file__).resolve().parents[1],autostart=False)
        try:self.assertFalse(other.enabled);self.assertEqual(other.status()['state'],'paused')
        finally:other.close()
    def test_logout_clears_encrypted_session_but_preserves_received_evidence(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='session',session={'cookies':[],'origins':[]}))
        self.sync.receive(dict(type='chat',job=self.chat()))
        accepted=set(self.sync.accepted);(self.sync.directory/'qr.png').write_bytes(b'old-qr')
        status=self.sync.logout()
        self.assertFalse(status['enabled']);self.assertEqual(status['state'],'idle');self.assertFalse(status['session_saved'])
        self.assertFalse((self.sync.directory/'qr.png').exists());self.assertEqual(self.sync.accepted,accepted)
        self.assertEqual([message['text'] for message in self.inbox.messages()],['1'])
        other=DesktopSync(self.inbox,self.sync.root,autostart=False)
        try:self.assertEqual(other.status()['state'],'idle');self.assertFalse(other.status()['session_saved']);self.assertEqual(other.accepted,accepted)
        finally:other.close()
    def test_queue_survives_rule_failure_and_retry(self):
        self.sync.enabled=True
        with patch('courseinbox.desktop_sync.ingest_web_message',side_effect=RuntimeError('private data')):self.sync.receive(dict(type='notice',job=self.job()))
        self.assertEqual(self.sync.status()['queued'],1);self.assertNotIn('private data',json.dumps(self.sync.status()))
        self.sync.retry_pending();self.assertEqual(self.sync.status()['queued'],0);self.assertEqual(len(self.inbox.messages()),1)
    def test_stale_worker_cannot_override_pause_or_new_session(self):
        self.sync.enabled=True;epoch=self.sync.epoch;self.sync.pause()
        self.sync.receive(dict(type='status',state='connected'),epoch)
        self.assertEqual(self.sync.status()['state'],'paused')
        self.sync.enabled=True;self.sync.state='connecting'
        self.sync.receive(dict(type='status',state='connected'),epoch)
        self.sync.receive(dict(type='notice',job=self.job()),epoch)
        self.assertEqual(self.sync.status()['state'],'connecting');self.assertEqual(self.inbox.messages(),[])
    def test_resume_retries_persisted_queue_before_browser_launch(self):
        self.sync.enabled=True
        with patch('courseinbox.desktop_sync.ingest_web_message',side_effect=RuntimeError()):self.sync.receive(dict(type='notice',job=self.job()))
        self.sync.pause();other=DesktopSync(self.inbox,self.sync.root,autostart=False)
        try:
            with patch.object(other,'_runtime',side_effect=RuntimeError()):other.start()
            self.assertEqual(other.status()['queued'],0);self.assertEqual(len(self.inbox.messages()),1)
        finally:other.close()
    def test_connection_error_takes_priority_over_incomplete_attachment(self):
        self.sync.enabled=True;self.sync.incomplete.add('old-notice')
        self.sync.receive(dict(type='status',state='expired',error='expired'))
        self.assertEqual(self.sync.status()['last_error'],'登录已失效，请重新扫码。')

    def test_transient_failure_preserves_session_and_exposes_safe_retry(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='session',session={'cookies':[],'origins':[]}))
        self.sync.receive(dict(type='status',state='retrying',error='network',stage='list_navigation',reason='timeout',retry_in=10))
        status=self.sync.status()
        self.assertEqual(status['state'],'retrying');self.assertTrue(status['session_saved'])
        self.assertEqual(status['error_stage'],'list_navigation');self.assertEqual(status['error_code'],'timeout');self.assertEqual(status['retry_in'],10)
        self.sync.receive(dict(type='status',state='connected',checked=True))
        status=self.sync.status();self.assertEqual(status['last_error'],'');self.assertEqual(status['retry_in'],0);self.assertTrue(status['last_checked']);self.assertIsNone(status['last_received']);self.assertIsNone(status['last_success'])

    def test_pending_source_cannot_claim_complete_check(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='status',state='connected'))
        self.sync.receive(dict(type='source',source='notice',state='connected',checked=True,pending_count=4,failed_count=0))
        status=self.sync.status()
        self.assertEqual(status['state'],'partial')
        self.assertTrue(status['sources']['notice']['last_checked'])
        self.assertIsNone(status['sources']['notice']['last_success'])
        self.assertIsNone(status['last_received'])
        self.sync.receive(dict(type='source',source='notice',state='connected',checked=True,pending_count=0,failed_count=0))
        self.assertTrue(self.sync.status()['sources']['notice']['last_success'])
    def test_failure_diagnostics_never_persist_arbitrary_worker_values(self):
        self.sync.enabled=True
        self.sync.receive(dict(type='status',state='retrying',error='network',stage='https://secret.invalid/?cookie=private',reason='private',retry_in=999999))
        self.assertNotIn('private',json.dumps(self.sync.status()))
        diagnostic=self.sync.directory/'diagnostic.json'
        if diagnostic.exists():self.assertNotIn('private',diagnostic.read_text(encoding='utf-8'))
        self.assertLessEqual(self.sync.status()['retry_in'],60)

    def test_unexpected_worker_exit_retries_saved_session_and_cannot_revive_pause(self):
        from unittest.mock import Mock
        self.sync.enabled=True;self.sync.state='connected'
        process=Mock(stdout=io.StringIO(''));process.poll.return_value=1;self.sync.process=process
        self.sync._read(process,self.sync.epoch)
        status=self.sync.status()
        self.assertEqual(status['state'],'retrying')
        self.assertEqual(status['error_code'],'worker_exit')
        self.assertFalse(status['worker_alive']);self.assertTrue(status['next_retry_at'])
        with patch('courseinbox.desktop_sync.time.monotonic',return_value=self.sync.restart_at+1),patch.object(self.sync,'_start',return_value={}) as start:
            self.sync._maintain_worker();start.assert_called_once_with(False,False)
        self.sync.pause()
        with patch.object(self.sync,'_start') as start:self.sync._maintain_worker();start.assert_not_called()

    def test_missing_runtime_exit_has_bounded_restarts(self):
        from unittest.mock import Mock
        self.sync.enabled=True;self.sync.restart_attempts=5
        process=Mock(stdout=io.StringIO(''));process.poll.return_value=1;self.sync.process=process
        self.sync._read(process,self.sync.epoch)
        self.assertEqual(self.sync.status()['state'],'error')
        self.assertIsNone(self.sync.status()['next_retry_at'])

    def test_stale_worker_heartbeat_is_visible_and_restarts_without_new_login(self):
        from unittest.mock import Mock
        self.sync.enabled=True;self.sync.state='connected'
        process=Mock();process.poll.return_value=None;self.sync.process=process
        self.sync.receive(dict(type='heartbeat'))
        with patch('courseinbox.desktop_sync.time.monotonic',return_value=self.sync.heartbeat_tick+121):
            self.assertEqual(self.sync.status()['freshness'],'stale')
            with patch.object(self.sync,'_start',return_value={}) as start:
                self.sync._maintain_worker();start.assert_called_once_with(False,False)

    def test_fresh_heartbeat_does_not_hide_a_stuck_source(self):
        from unittest.mock import Mock
        self.sync.enabled=True;self.sync.state='connected'
        process=Mock();process.poll.return_value=None;self.sync.process=process
        self.sync.receive(dict(type='source',source='notice',state='syncing'))
        with patch('courseinbox.desktop_sync.time.monotonic',return_value=self.sync.source_ticks['notice']+301):
            self.sync.receive(dict(type='heartbeat'))
            self.assertEqual(self.sync.status()['sources']['notice']['freshness'],'stale')
            self.assertEqual(self.sync.status()['freshness'],'stale')
            with patch.object(self.sync,'_start',return_value={}) as start:
                self.sync._maintain_worker();start.assert_called_once_with(False,False)

    def test_recheck_uses_live_worker_and_retry_queue_without_resetting_login(self):
        from unittest.mock import Mock
        self.sync.enabled=True
        process=Mock();process.poll.return_value=None;self.sync.process=process
        with patch.object(self.sync,'command') as command,patch.object(self.sync,'retry_pending') as retry:
            self.sync.recheck();command.assert_called_once_with(dict(type='recheck'));retry.assert_called_once()
        self.assertTrue(self.sync.enabled)

    def test_detail_coverage_gap_cannot_claim_complete_success(self):
        self.sync.enabled=True;self.sync.receive(dict(type='status',state='connected'))
        self.sync.receive(dict(type='source',source='task_center',state='connected',checked=True,pending_count=0,failed_count=0,coverage='list_only',unsupported_detail_count=2,detail_pending_count=0))
        source=self.sync.status()['sources']['task_center']
        self.assertEqual(source['state'],'partial');self.assertEqual(source['coverage'],'list_only')
        self.assertEqual(source['unsupported_detail_count'],2);self.assertIsNone(source['last_complete_success'])
        self.assertTrue(source['last_progress'])

    def test_discovered_sections_merge_validate_and_persist_before_next_full_sweep(self):
        self.sync.enabled=True
        first='a'*24;second='b'*24
        self.sync.receive(dict(type='source',source='task_center',state='syncing',discovered_sections=[first,first,'private',1,{},'A'*24]))
        self.sync.receive(dict(type='source',source='task_center',state='partial',discovered_sections=[second]))
        source=self.sync.status()['sources']['task_center']
        self.assertEqual(source['discovered_sections'],[first,second]);self.assertFalse(source['discovery_complete'])
        self.assertIsNone(source['last_complete_success'])
        source['discovered_sections'].clear()
        self.assertEqual(self.sync.status()['sources']['task_center']['discovered_sections'],[first,second])
        other=DesktopSync(self.inbox,self.sync.root,autostart=False)
        try:self.assertEqual(other.status()['sources']['task_center']['discovered_sections'],[first,second])
        finally:other.close()
        self.assertNotIn('private',(self.sync.directory/'config.json').read_text(encoding='utf-8'))

    def test_discovered_sections_are_bounded_to_two_hundred_valid_keys(self):
        self.sync.enabled=True
        keys=[f'{value:024x}' for value in range(220)]
        self.sync.receive(dict(type='source',source='task_center',state='partial',discovered_sections=keys))
        self.assertEqual(self.sync.status()['sources']['task_center']['discovered_sections'],keys[-200:])

    def test_inventory_epoch_resets_only_for_fresh_login_and_logout_and_survives_reload(self):
        self.sync.enabled=True
        section='c'*24
        self.sync.receive(dict(type='source',source='task_center',state='partial',checked=True,discovered_sections=[section],discovery_complete=True))
        self.assertEqual(self.sync.status()['inventory_epoch'],0)
        with patch.object(self.sync,'_runtime',side_effect=RuntimeError()):fresh=self.sync.start(fresh=True)
        self.assertEqual(fresh['inventory_epoch'],1);self.assertEqual(fresh['sources']['task_center']['discovered_sections'],[]);self.assertFalse(fresh['sources']['task_center']['discovery_complete'])
        self.sync.receive(dict(type='source',source='task_center',state='partial',checked=True,discovered_sections=[section],discovery_complete=True))
        other=DesktopSync(self.inbox,self.sync.root,autostart=False)
        try:
            self.assertEqual(other.status()['inventory_epoch'],1)
            with patch.object(other,'_runtime',side_effect=RuntimeError()):resumed=other.start()
            self.assertEqual(resumed['inventory_epoch'],1);self.assertEqual(resumed['sources']['task_center']['discovered_sections'],[section]);self.assertTrue(resumed['sources']['task_center']['discovery_complete'])
            logged_out=other.logout();self.assertEqual(logged_out['inventory_epoch'],2);self.assertEqual(logged_out['sources']['task_center']['discovered_sections'],[]);self.assertFalse(logged_out['sources']['task_center']['discovery_complete'])
            reloaded=DesktopSync(self.inbox,self.sync.root,autostart=False)
            try:self.assertEqual(reloaded.status()['inventory_epoch'],2);self.assertEqual(reloaded.status()['state'],'idle');self.assertEqual(reloaded.status()['sources']['task_center']['discovered_sections'],[])
            finally:reloaded.close()
        finally:other.close()

    def test_partial_attachment_is_a_visible_coverage_gap_without_repeated_download(self):
        self.sync.enabled=True;job=self.job();job['attachments']=[dict(name='阅读材料.pdf',url='',size=3,status='partial',text='可读部分',error='仅部分文字')]
        self.sync.receive(dict(type='notice',job=job))
        self.assertEqual(len(self.inbox.messages()),1)
        self.assertEqual(self.sync.status()['incomplete'],1)
        self.assertIn(job['message_id'],self.sync.accepted,'a known partial extraction is not repaired by redownloading every minute')

    def test_unsupported_attachment_preserves_notice_and_failed_status(self):
        self.sync.enabled=True;job=self.job();job['attachments']=[dict(name='说明.docx',url='https://d0.cldisk.com/download/'+'a'*32,size=3,content_base64=base64.b64encode(b'bad').decode())]
        self.sync.receive(dict(type='notice',job=job));stored=self.inbox.messages()[0]
        self.assertEqual(stored['external']['attachments'][0]['status'],'failed');self.assertNotIn('content_base64',json.dumps(stored));self.assertNotIn(job['message_id'],self.sync.accepted)

    @unittest.skipUnless(__import__('os').name=='nt','Windows DPAPI')
    def test_session_is_encrypted_for_current_windows_user(self):
        from courseinbox.session_crypto import unseal
        self.sync.enabled=True;value={'cookies':[{'name':'test-cookie','value':'secret-cookie-value'}],'origins':[]}
        self.sync.receive(dict(type='session',session=value));raw=(self.sync.directory/'session.bin').read_bytes()
        self.assertNotIn(b'secret-cookie-value',raw);self.assertEqual(json.loads(unseal(raw)),value)

class DesktopApiTests(unittest.TestCase):
    def setUp(self):
        from courseinbox.http import create_server
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.inbox=Inbox(self.root/'db.sqlite3');self.token='local-test-token';self.server=create_server('127.0.0.1',0,self.inbox,self.token);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,name,body=None,token=None,origin=None):
        headers={'Authorization':'Bearer '+(token or self.token),'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        request=urllib.request.Request(self.url+'/api/chaoxing/desktop/'+name,None if body is None else json.dumps(body).encode(),headers)
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,response.read()
        except urllib.error.HTTPError as error:return error.code,error.read()
    def test_controls_require_main_token_and_loopback(self):
        from courseinbox.chaoxing import scoped_token
        self.assertEqual(self.request('status',token=scoped_token(self.token))[0],401)
        self.assertEqual(self.request('login',{},token=scoped_token(self.token))[0],401)
        self.assertEqual(self.request('logout',{},token=scoped_token(self.token))[0],401)
        with patch('courseinbox.http.ipaddress.ip_address') as address:
            address.return_value.is_loopback=False
            self.assertEqual(self.request('status')[0],403)
        self.assertEqual(self.request('pause',{},origin='https://evil.example')[0],403)
    def test_logout_endpoint_removes_session_and_is_idempotent(self):
        sync=self.server.desktop_sync;sync.enabled=True;sync.receive(dict(type='session',session={'cookies':[],'origins':[]}))
        self.assertTrue(sync.status()['session_saved'])
        code,raw=self.request('logout',{})
        self.assertEqual(code,200);self.assertFalse(json.loads(raw)['session_saved'])
        self.assertEqual(self.request('logout',{})[0],200)
    def test_qr_is_local_authenticated_and_removed_after_pause(self):
        sync=self.server.desktop_sync;sync.enabled=True;sync.state='waiting_scan';sync.qr_ready=True;image=b'\x89PNG\r\n\x1a\nfixture-qr';(sync.directory/'qr.png').write_bytes(image)
        self.assertEqual(self.request('qr'),(200,image))
        self.assertEqual(self.request('qr',token='wrong')[0],401)
        self.assertEqual(self.request('pause',{})[0],200);self.assertEqual(self.request('qr')[0],404)
    def test_login_starts_dedicated_worker_not_existing_browser(self):
        with patch.object(self.server.desktop_sync,'start',return_value={'state':'connecting'}) as start:
            self.assertEqual(self.request('login',{})[0],200);start.assert_called_once_with(fresh=True,visible=False)
            self.assertEqual(self.request('login',{'visible':'unsafe'})[0],400)
