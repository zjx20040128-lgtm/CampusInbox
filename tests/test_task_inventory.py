import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox, ValidationError
from courseinbox.desktop_sync import DesktopSync
from courseinbox.desktop_alerts import DesktopAlerts


class TaskInventoryTests(unittest.TestCase):
    def test_processed_attachment_receipt_is_not_missing_after_list_recheck(self):
        from courseinbox.chaoxing import ingest_web_message
        file=dict(name='image.bmp',url='https://d0.cldisk.com/download/'+'a'*32,status='listed')
        job=self.job(attachments=[file])
        self.manifest([job])
        stored=dict(job,attachments=[dict(file,status='skipped',error='原文件已关联，未自动提取文字。')])
        result=ingest_web_message(self.inbox,stored)
        self.inbox.confirm(result['proposals'][0]['id'])
        item=self.sync.task_inventory()['items'][0]
        self.assertEqual(item['state'],'confirmed')
        self.assertTrue(item['media_pending'])
        changed=dict(job,text='新增要求：提交两份报告',description='新增要求：提交两份报告')
        self.manifest([changed])
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'missing')

    def test_attention_filters_settled_sources_before_pagination_without_erasing_read_gaps(self):
        items=[dict(key=str(i),state='confirmed' if i<20 else 'pending',detail_state='manual',media_pending=False) for i in range(22)]
        snapshot=dict(items=items,total=22,counts=dict(confirmed=20,pending=2),manual_details=22,detail_pending=0)
        with patch.object(self.sync.inventory,'snapshot',return_value=snapshot):
            report=self.sync.task_inventory(limit=20,attention_only=True)
        self.assertEqual([item['key'] for item in report['items']],['20','21'])
        self.assertEqual(report['total'],2)
        self.assertEqual(report['source_total'],22)
        self.assertEqual(report['attention_manual_details'],2)
        self.assertEqual(report['manual_details'],22)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox = Inbox(Path(self.tmp.name) / 'inbox.sqlite3')
        self.sync = DesktopSync(self.inbox, Path(__file__).resolve().parents[1], autostart=False)
        self.addCleanup(self.sync.close)
        self.sync.enabled = True

    def job(self, number=43, **changes):
        result = dict(kind='task_center', message_id=f'task_inventory_{number}', title='实验报告', text='完成实验报告',
                      course='课程一', conversation='课程一', sender='', direction='received', display_time='',
                      captured_at='2026-10-19T09:00:00+08:00', task_type='assignment', deadline=None,
                      url=f'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId={number}',
                      field_evidence={'title': '实验报告'}, detail_state='read')
        result.update(changes)
        return result

    def manifest(self, jobs, complete=True):
        self.sync.receive(dict(type='task_inventory', phase='catalog', courses=[dict(course_id='1', class_id='2', course='课程一', course_index=1)], truncated=False))
        self.sync.receive(dict(type='task_inventory', phase='section', course_id='1', class_id='2', kind='assignment', jobs=jobs, complete=complete))

    def test_missing_receipt_becomes_pending_then_confirmed_without_creating_tasks(self):
        job = self.job()
        self.manifest([job])
        report = self.sync.task_inventory()
        self.assertEqual(report['counts']['missing'], 1)
        self.assertEqual(report['sections'][1]['state'], 'unchecked')
        self.sync.receive(dict(type='task_center', job=job))
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'pending')
        self.assertEqual(self.inbox.tasks(), [])
        self.inbox.confirm(self.inbox.proposals()[0]['id'])
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'confirmed')

    def test_archived_and_cleared_records_are_not_missing_or_resurrected(self):
        job = self.job(deadline='2025-01-01', field_evidence={'title': '实验报告', 'deadline': '截止2025-01-01'})
        self.manifest([job])
        self.sync.receive(dict(type='task_center', job=job))
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'archived')
        self.inbox.clear_messages([self.inbox.messages()[0]['id']])
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'cleared')
        with patch.object(self.sync, 'command') as command:
            self.assertEqual(self.sync.repair_tasks()['requested'], 0)
            command.assert_not_called()
        self.assertEqual(self.inbox.proposals(), [])

    def test_new_content_is_missing_even_when_old_task_exists_and_countdown_is_not(self):
        job = self.job()
        self.manifest([job]); self.sync.receive(dict(type='task_center', job=job))
        self.inbox.confirm(self.inbox.proposals()[0]['id'])
        changed = self.job(message_id='task_changed', text='完成实验报告；剩余10小时', deadline='2026-12-01', field_evidence={'title': '实验报告', 'deadline': '截止2026-12-01'})
        self.manifest([changed])
        self.assertEqual(self.sync.task_inventory()['counts']['missing'], 1)
        self.sync.receive(dict(type='task_center', job=changed))
        repeated = dict(changed, message_id='task_changed_again', text='完成实验报告；剩余9小时')
        self.manifest([repeated])
        self.assertEqual(self.sync.task_inventory()['counts']['missing'], 0)
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'pending')
        self.assertEqual(len(self.inbox.tasks()), 1)

    def test_failed_sections_keep_previous_entries_and_state_survives_restart(self):
        self.manifest([self.job()])
        self.sync.receive(dict(type='task_inventory', phase='failure', course_id='1', class_id='2', kind='assignment', reason='timeout'))
        report = self.sync.task_inventory()
        self.assertEqual(report['total'], 1)
        self.assertEqual(report['sections'][0]['state'], 'failed')
        other = DesktopSync(self.inbox, Path(__file__).resolve().parents[1], autostart=False)
        self.addCleanup(other.close)
        self.assertEqual(other.task_inventory()['total'], 1)
        self.sync.logout()
        self.assertEqual(self.sync.task_inventory()['total'], 0)

    def test_repair_targets_only_missing_or_readable_details_and_throttles_auto_retry(self):
        missing = self.job()
        unsupported = self.job(44, url='https://mooc1.chaoxing.com/mooc2/work/unsupported?courseId=1&classId=2&workId=44', detail_state='skipped')
        self.manifest([missing, unsupported])
        self.sync.receive(dict(type='task_center', job=unsupported))
        with patch.object(self.sync, 'command') as command:
            self.assertEqual(self.sync.repair_tasks()['requested'], 1)
            self.assertEqual(command.call_args.args[0], dict(type='repair_tasks', keys=['1|2|assignment|43']))
            self.sync.repair_tasks(automatic=True)
            self.assertEqual(sum(call.args[0]['type']=='repair_tasks' for call in command.call_args_list), 1)
        self.assertEqual(self.sync.task_inventory()['items'][1]['detail_state'], 'manual')
        with self.assertRaises(ValidationError): self.sync.repair_tasks(['9|2|assignment|43'])

    def test_assignment_static_reader_is_retryable_and_exposes_time_warning(self):
        job=self.job(url='https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&classId=2&workId=43&answerId=7',detail_state='unavailable')
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(self.sync.task_inventory()['items'][0]['detail_state'],'pending')
        detailed=dict(job,text='提交报告。\n作答时间:10-23 23:35至10-28 23:35',description='提交报告。',detail_state='read',field_evidence={'title':'实验报告','deadline':'作答时间:10-23 23:35至10-28 23:35'},detail_error='作答时间未包含完整年份，截止时间请核对原文。')
        self.manifest([detailed]);self.sync.receive(dict(type='task_center',job=detailed))
        item=self.sync.task_inventory()['items'][0]
        self.assertEqual(item['detail_state'],'read')
        self.assertIn('年份',item['detail_error'])
        self.assertIsNone(item['deadline'])
        self.assertTrue(item['deadline_pending'])
        self.assertEqual(self.sync.task_inventory()['deadline_pending'],1)

    def test_task_inline_image_enters_extraction_and_clears_gap_only_after_ocr(self):
        import base64
        job=self.job(detail_state='read',attachments=[dict(name='作业图片1.png',url='https://p.ananas.chaoxing.com/test/requirements.png',kind='inline_image',status='listed')])
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.assertTrue(self.sync.task_inventory()['items'][0]['media_pending'])
        with patch('courseinbox.desktop_sync.extract_file',return_value=('图片要求：提交实验报告PDF。','test')):
            self.sync.receive(dict(type='task_center',job=dict(job,attachments=[dict(job['attachments'][0],content_base64=base64.b64encode(b'fixture image').decode())])))
        self.assertFalse(self.sync.task_inventory()['items'][0]['media_pending'])
        self.assertIn('提交实验报告PDF',self.inbox.messages()[0]['text'])
        self.assertEqual(self.inbox.tasks(),[])

    def test_submitted_detail_without_new_work_is_historical_not_unrecognized(self):
        from courseinbox.chaoxing import normalize_web_message
        job=self.job(detail_state='read',platform_status='待批阅',description='已提交作业的完整说明')
        self.manifest([job])
        value=normalize_web_message(job);value['candidates']=[]
        self.inbox.ingest(**value)
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'archived')
        self.assertEqual(self.inbox.tasks(),[])

    def test_long_task_requirements_do_not_fail_intake(self):
        paragraph='比较算法性能并提交实验报告。'*45
        job=self.job(text=paragraph,description=paragraph,detail_state='read')
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'pending')
        candidate=self.inbox.proposals()[0]['candidate']
        self.assertGreater(len(candidate['requirements']),1)
        self.assertTrue(all(len(text)<=180 for text in candidate['requirements']))
        self.assertEqual(''.join(candidate['requirements']),paragraph)
        self.assertEqual(self.inbox.messages()[0]['external']['description'],paragraph)

    def test_successful_retry_removes_stale_extraction_failure(self):
        from courseinbox.chaoxing import normalize_web_message
        job=self.job(description='提交实验报告。',detail_state='read')
        self.manifest([job]);value=normalize_web_message(job)
        value['external']['extraction_warning']='旧提取失败';value['candidates']=[]
        self.inbox.ingest(**value)
        self.assertEqual(self.sync.repair_tasks()['reextracted'],1)
        self.assertNotIn('extraction_warning',self.inbox.messages()[0]['external'])

    def test_explicit_read_only_link_makes_an_operation_entry_retryable(self):
        job=self.job(url='https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=43&answerId=7',
                     detail_url='https://mooc1.chaoxing.com/mooc2/work/view?courseId=1&classId=2&workId=43',detail_state='unavailable')
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(self.sync.task_inventory()['items'][0]['detail_state'],'pending')
        with patch.object(self.sync,'command') as command:
            self.assertEqual(self.sync.repair_tasks()['requested'],1)
            self.assertEqual(command.call_args.args[0]['keys'],['1|2|assignment|43'])

    def test_read_only_link_cannot_change_identity_or_enter_an_answer_page(self):
        from courseinbox.chaoxing import normalize_web_message
        for link in ('https://mooc1.chaoxing.com/mooc2/work/detail?courseId=9&classId=2&workId=43',
                     'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId=43&answerId=7',
                     'https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=43',
                     'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId=43&workId=99'):
            with self.subTest(link=link),self.assertRaises(ValidationError):normalize_web_message(self.job(detail_url=link))

    def test_extracted_task_attachment_preserves_text_without_confirming_task(self):
        job=self.job(detail_state='read',description='要求见附件',attachments=[dict(name='作业要求.txt',url='https://d0.cldisk.com/download/'+'a'*32,status='extracted',text='请提交报告和源码。')])
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(len(self.inbox.messages()),1)
        self.assertIn('报告和源码',self.inbox.messages()[0]['text'])
        self.assertTrue(any('报告和源码' in r for r in self.inbox.proposals()[0]['candidate']['requirements']))
        self.assertFalse(self.sync.task_inventory()['items'][0]['media_pending'])
        self.assertEqual(self.inbox.tasks(),[])
        replay=self.job(detail_state='read',description='要求见附件',attachments=[dict(name='作业要求.txt',url='https://d0.cldisk.com/download/'+'a'*32,status='listed')])
        self.manifest([replay])
        self.assertFalse(self.sync.task_inventory()['items'][0]['media_pending'],'same attachment listing must not discard extracted receipt')
        self.assertNotEqual(self.sync.task_inventory()['items'][0]['state'],'missing')
        replay['media_pending_count']=1
        self.manifest([replay])
        self.assertTrue(self.sync.task_inventory()['items'][0]['media_pending'],'a newly observed unread image must remain visible')

    def test_failed_task_attachment_stays_retryable_and_incomplete(self):
        job=self.job(detail_state='read',attachments=[dict(name='作业要求.pdf',url='https://d0.cldisk.com/download/'+'b'*32,status='failed',text='',error='下载失败')])
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(self.sync.status()['incomplete'],1)
        self.assertTrue(self.sync.task_inventory()['items'][0]['media_pending'])
        self.assertNotIn(job['message_id'],self.sync.accepted)
        job['attachments'][0].update(status='extracted',text='请提交实验报告。',error='')
        self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(len(self.inbox.messages()),1)
        self.assertIn('实验报告',self.inbox.messages()[0]['external']['attachments'][0]['text'])
        self.assertEqual(self.sync.status()['incomplete'],0)
        self.assertFalse(self.sync.task_inventory()['items'][0]['media_pending'])
        self.assertNotEqual(self.sync.task_inventory()['items'][0]['state'],'missing')
        job['attachments'][0]['text']='另一份不相容要求。'
        self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(self.inbox.messages()[0]['external']['attachments'][0]['text'],'请提交实验报告。')
        self.assertEqual(self.sync.status()['incomplete'],1)

    def test_task_attachment_upgrade_keeps_ignored_and_cleared_records_settled(self):
        for number,terminal in ((70,'ignored'),(71,'cleared'),(72,'cleared_deleted')):
            with self.subTest(terminal=terminal):
                job=self.job(number,detail_state='read',attachments=[dict(name='作业要求.txt',url='https://d0.cldisk.com/download/'+'c'*32,status='failed')])
                self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
                message=next(m for m in self.inbox.messages() if m['external']['message_id']==job['message_id'])
                if terminal in ('ignored','cleared_deleted'):
                    proposal=next(p for p in self.inbox.proposals() if p['message_id']==message['id']);self.inbox.dismiss(proposal['id'])
                if terminal!='ignored':self.inbox.clear_messages([message['id']])
                previous_pending={p['id'] for p in self.inbox.proposals() if p['message_id']==message['id'] and p['status']=='pending'}
                job['attachments'][0].update(status='extracted',text='提交报告PDF。')
                self.sync.receive(dict(type='task_center',job=job))
                row=next(i for i in self.sync.task_inventory()['items'] if i['key'].endswith('|'+str(number)))
                self.assertEqual(row['state'],'cleared' if terminal.startswith('cleared') else terminal)
                self.assertEqual({p['id'] for p in self.inbox.proposals() if p['message_id']==message['id'] and p['status']=='pending'},previous_pending)

    def test_newly_observed_media_is_not_hidden_by_an_old_successful_receipt(self):
        job=self.job(detail_state='read',description='完成实验报告',attachments=[])
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        job['media_pending_count']=1
        with patch.object(self.sync,'command') as command:self.sync.receive(dict(type='task_center',job=job))
        self.assertEqual(self.inbox.messages()[0]['external']['media_pending_count'],1)
        self.assertTrue(self.sync.task_inventory()['items'][0]['media_pending'])
        self.assertEqual(self.sync.status()['incomplete'],1)
        self.assertFalse(command.call_args.args[0]['media_complete'])

    def test_identity_rejection_is_visible_and_never_matches_by_title(self):
        unknown = self.job(url='https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&workId=43')
        wrong = self.job(44, url='https://mooc1.chaoxing.com/mooc2/work/detail?courseId=9&classId=2&workId=44')
        self.manifest([unknown, wrong])
        report = self.sync.task_inventory()
        self.assertEqual(report['total'], 0)
        self.assertEqual(report['sections'][0]['unidentified_count'], 2)
        self.assertEqual(report['sections'][0]['state'], 'partial')

    def test_reextracts_saved_task_automatically_without_reviving_ignored_proposal(self):
        job = self.job()
        self.manifest([job])
        with patch.object(self.inbox, '_proposal', side_effect=ValidationError('invalid extraction')):
            self.sync.receive(dict(type='task_center', job=job))
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'unrecognized')
        with patch.object(self.sync, 'command'):
            self.sync.repair_tasks()
        self.assertEqual(len(self.inbox.proposals()), 1)
        proposal = self.inbox.proposals()[0]
        self.inbox.dismiss(proposal['id'])
        with patch.object(self.sync, 'command') as command:
            self.assertEqual(self.sync.repair_tasks()['requested'], 0)
            command.assert_not_called()
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'], 'ignored')

    def test_failed_empty_section_can_be_retried_without_arbitrary_urls(self):
        self.manifest([])
        self.sync.receive(dict(type='task_inventory', phase='failure', course_id='1', class_id='2', kind='exam', reason='timeout'))
        with patch.object(self.sync, 'command') as command:
            result=self.sync.repair_tasks(sections=['1|2|exam'])
            self.assertEqual(result['sections_requested'],1)
            self.assertEqual(command.call_args.args[0],dict(type='repair_sections',keys=['1|2|exam']))
        with self.assertRaises(ValidationError):self.sync.repair_tasks(sections=['9|2|exam'])

    def test_lost_delivery_then_duplicate_repair_produces_one_draft_and_one_alert_handoff(self):
        alerts=DesktopAlerts(self.inbox)
        key=hashlib.sha256(b'1|2|assignment').hexdigest()[:24]
        status=dict(enabled=True,inventory_epoch=0,sources={'task_center':dict(discovered_sections=[key])})
        self.assertEqual(alerts.poll('2026-10-19T08:00:00+08:00',sync_status=status)['events'],[])
        job=self.job()
        self.manifest([job])
        with patch.object(self.sync,'command') as command:
            self.sync.repair_tasks()
            self.assertEqual(command.call_args.args[0]['keys'],['1|2|assignment|43'])
        self.sync.receive(dict(type='task_center',job=job))
        self.sync.receive(dict(type='task_center',job=dict(job,message_id='retry_same_content')))
        self.assertEqual(len(self.inbox.messages()),1)
        self.assertEqual(len(self.inbox.proposals()),1)
        events=alerts.poll('2026-10-19T09:01:00+08:00',sync_status=status)['events']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['kind'],'new_pending')
        alerts.ack([events[0]['id']])
        self.assertEqual(alerts.poll('2026-10-19T09:02:00+08:00',sync_status=status)['events'],[])
        self.assertEqual(self.sync.task_inventory()['counts']['missing'],0)

    def test_preliminary_or_unread_list_cannot_downgrade_cleared_enriched_receipt(self):
        raw=self.job(detail_state='list_only')
        self.manifest([raw],complete=False)
        detailed=dict(raw,message_id='task_inventory_detailed',detail_state='read',description='详细材料要求',text='完成实验报告\n详细材料要求')
        self.sync.receive(dict(type='task_center',job=detailed))
        self.sync.receive(dict(type='task_inventory',phase='section',course_id='1',class_id='2',kind='assignment',jobs=[detailed],complete=True))
        self.inbox.clear_messages([self.inbox.messages()[0]['id']])
        self.manifest([raw],complete=False)
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'cleared')
        self.sync.receive(dict(type='task_inventory',phase='failure',course_id='1',class_id='2',kind='assignment',reason='timeout'))
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'cleared')
        self.sync.receive(dict(type='task_center',job=dict(raw,detail_state='skipped')))
        self.assertEqual(len(self.inbox.messages(include_hidden=True)),1)
        self.assertEqual(self.inbox.messages(),[])
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'cleared')
        previous={p['id'] for p in self.inbox.proposals()}
        changed=dict(raw,message_id='genuine_new_requirement',text='完成实验报告并补交代码',detail_state='skipped')
        self.manifest([changed],complete=False)
        self.sync.receive(dict(type='task_center',job=changed))
        self.assertEqual(len([p for p in self.inbox.proposals() if p['id'] not in previous]),1,'genuine new requirements must remain reviewable')

    def test_status_only_evidence_of_confirmed_task_is_not_failed_extraction(self):
        job=self.job(platform_status='未提交',text='完成实验报告；未提交')
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        self.inbox.confirm(self.inbox.proposals()[0]['id'])
        updated=dict(job,message_id='inventory_status_update',platform_status='已提交',text='完成实验报告；已提交',captured_at='2026-10-19T09:01:00+08:00')
        self.manifest([updated]);self.sync.receive(dict(type='task_center',job=updated))
        self.assertEqual(self.inbox.proposals(),[])
        self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'confirmed')

    def test_unread_inline_media_is_visible_per_task(self):
        job=self.job(media_pending_count=2)
        self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
        report=self.sync.task_inventory()
        self.assertTrue(report['items'][0]['media_pending'])
        self.assertEqual(report['manual_details'],1)
        self.assertTrue(any('图片或媒体' in warning for warning in self.inbox.proposals()[0]['candidate']['warnings']))
        self.inbox.reanalyze(self.inbox.messages()[0]['id'])
        self.assertTrue(any('图片或媒体' in warning for warning in self.inbox.proposals()[0]['candidate']['warnings']))

    def test_same_list_replay_keeps_detail_receipt_but_new_requirements_need_reading(self):
        raw=self.job(detail_state='skipped')
        self.manifest([raw],complete=False)
        detailed=dict(raw,text='完成实验报告并提交说明',detail_state='read')
        self.sync.receive(dict(type='task_center',job=detailed))
        self.sync.receive(dict(type='task_center',job=raw))
        report=self.sync.task_inventory()
        self.assertEqual(report['items'][0]['detail_state'],'read')
        self.assertEqual(report['detail_pending'],0)
        self.assertEqual(self.sync.repair_tasks(automatic=True)['requested'],0)
        changed=dict(raw,text='完成实验报告并补交代码',message_id='changed_requirements')
        self.manifest([changed],complete=False)
        self.assertEqual(self.sync.task_inventory()['items'][0]['detail_state'],'pending')

    def test_status_only_replay_cannot_revive_ignored_or_cleared_content(self):
        for number,terminal in ((50,'ignored'),(51,'cleared'),(52,'cleared_archive')):
            with self.subTest(terminal=terminal):
                job=self.job(number,platform_status='未提交',text='完成实验报告；未提交')
                if terminal=='cleared_archive':job.update(deadline='2025-01-01',field_evidence={'title':'实验报告','deadline':'截止2025-01-01'})
                self.manifest([job]);self.sync.receive(dict(type='task_center',job=job))
                message=next(m for m in self.inbox.messages() if m.get('external',{}).get('message_id')==job['message_id'])
                if terminal=='ignored':
                    proposal=next(p for p in self.inbox.proposals() if p['message_id']==message['id']);self.inbox.dismiss(proposal['id'])
                else:self.inbox.clear_messages([message['id']])
                before={p['id'] for p in self.inbox.proposals()}
                changed=dict(job,message_id=f'status_only_{number}',platform_status='已提交',text='完成实验报告；已提交',captured_at='2026-10-19T09:01:00+08:00')
                self.manifest([changed]);self.sync.receive(dict(type='task_center',job=changed))
                self.assertEqual(self.sync.task_inventory()['items'][0]['state'],'ignored' if terminal=='ignored' else 'cleared')
                with patch.object(self.sync,'command'):self.sync.repair_tasks()
                self.assertEqual({p['id'] for p in self.inbox.proposals()},before)


if __name__ == '__main__': unittest.main()
