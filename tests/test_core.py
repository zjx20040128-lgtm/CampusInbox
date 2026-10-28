import tempfile
import json
import unittest
from pathlib import Path
from courseinbox.core import Inbox, Conflict, ValidationError, parse_message

AT = '2026-10-03T16:00:00+08:00'
PRECLASS = json.loads((Path(__file__).resolve().parents[1]/'samples'/'preclass-reading.json').read_text(encoding='utf-8'))

TEXT = '《软件工程》 第三次作业：请提交实验报告、源代码。截止：2026年10月12日 23:59。'

class ParsingTests(unittest.TestCase):
    def test_relative_dates_use_message_time_not_today(self):
        p = parse_message('《高等数学》 第三次作业，请明天18:30前提交。', '2026-01-31T22:00:00+08:00')[0]
        self.assertEqual(p['deadline'], '2026-02-01T18:30:00+08:00')
    def test_date_without_time_is_not_invented(self):
        p = parse_message('《高等数学》 第三次作业，10月12日前提交。', AT)[0]
        self.assertEqual(p['deadline'], '2026-10-12')
        self.assertEqual(p['date_precision'], 'date')
    def test_extension_uses_new_deadline_not_old(self):
        p = parse_message('《软件工程》 第三次作业原截止10月12日23:59，现延期到10月15日18:00。', AT)[0]
        self.assertEqual(p['deadline'], '2026-10-15T18:00:00+08:00')
        self.assertEqual(p['operation'], 'update')
    def test_missing_deadline_and_impossible_date_are_flagged(self):
        for text in ['《数据结构》 实验报告请及时提交', '《数据结构》 实验报告截止2月30日18:00']:
            p = parse_message(text, AT)[0]
            self.assertIsNone(p['deadline'])
            self.assertTrue(p['warnings'])
    def test_date_before_deadline_word_is_extracted(self):
        p=parse_message('《数学》第一次作业，10月12日18:00截止。',AT)[0]
        self.assertEqual(p['deadline'],'2026-10-12T18:00:00+08:00')
    def test_negation_and_material_cancellation_keep_task_active(self):
        for text in ['《数学》第一次作业，不取消，截止10月12日18:00。',
                     '《数学》第一次作业，取消纸质版，仍需提交电子版，截止10月12日18:00。']:
            p=parse_message(text,AT)[0]
            self.assertNotEqual(p['operation'],'cancel')
            self.assertTrue(p['warnings'])
        material=parse_message('《数学》第一次作业，取消纸质版，仍需提交电子版，截止10月12日18:00。',AT)[0]
        self.assertIn('电子版',material['requirements'])
    def test_explicit_task_cancellation_still_works(self):
        for text in ['《数学》第一次作业已取消，不用提交。','《数学》取消第一次作业。']:
            self.assertEqual(parse_message(text,AT)[0]['operation'],'cancel')
    def test_plain_notice_not_turned_into_task(self):
        self.assertEqual(parse_message('同学们节日快乐，请注意安全。', AT), [])
    def test_real_notice_request_shapes_are_actionable_without_invented_time(self):
        survey=parse_message('《统计课》请大家如实填写问卷，谢谢！',AT)[0]
        self.assertEqual(survey['title'],'填写问卷')
        self.assertIsNone(survey['deadline'])
        class_kit=parse_message('《绘图课》明天上课需要绘图，请大家带着电脑或者纸和笔。',AT)[0]
        self.assertEqual(class_kit['title'],'上课准备')
        self.assertEqual(class_kit['deadline'],'2026-10-04')
        group=parse_message('《软件工程》请大家扫码进课程微信群。',AT)[0]
        self.assertEqual(group['title'],'加入课程群')
        self.assertIsNone(group['deadline'])
        self.assertEqual(parse_message('《统计课》如果愿意可以带电脑。',AT),[])
    def test_assignment_start_and_end_choose_end_time(self):
        text='作业：《自然辩证法》作业一\n开始时间：2026-09-15 16:25\n结束时间：2026-09-15 17:45'
        self.assertEqual(parse_message(text,'2026-09-15T16:25:00+08:00')[0]['deadline'],'2026-09-15T17:45:00+08:00')
    def test_checklist_preserves_deliverables(self):
        p = parse_message(TEXT, AT)[0]
        self.assertIn('实验报告', p['requirements'])
        self.assertIn('源代码', p['requirements'])

    def test_ocr_preclass_notice_creates_reading_and_discussion_requirements(self):
        candidates=parse_message(PRECLASS['text'],PRECLASS['captured_at'])
        self.assertEqual(len(candidates),1)
        task=candidates[0]
        self.assertEqual(task['course'],'软件工程高级管理技术')
        self.assertIn('第二次课',task['title'])
        self.assertIn('阅读',task['title'])
        self.assertEqual(task['kind'],'other')
        self.assertEqual(task['deadline'],'2026-10-09')
        self.assertEqual(task['date_precision'],'date')
        self.assertTrue(any('阅读' in item for item in task['requirements']))
        self.assertTrue(any('研讨' in item and '准备' in item for item in task['requirements']))
        self.assertTrue(any('课前阅读说明' in item for item in task['requirements']))
        self.assertTrue(any('附件' in warning and '正文' in warning for warning in task['warnings']))
        self.assertTrue(any('上课' in warning and '时' in warning for warning in task['warnings']))
        self.assertFalse(task['matchable'])
        self.assertEqual(len(task['requirements']),3)
    def test_reading_deadline_uses_instruction_instead_of_copied_publication_date(self):
        text='10-08 12:06\n《计算机基础》请大家提前阅读两份材料，做好讨论准备。请在明天上课前完成。'
        candidates=parse_message(text,'2026-10-08T12:56:00+08:00')
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['deadline'],'2026-10-09')
    def test_preclass_reading_keeps_unknown_next_class_date(self):
        candidates=parse_message('《英语》请大家在下次课前预习第二章，具体要求请见附件。',AT)
        self.assertEqual(len(candidates),1)
        self.assertIsNone(candidates[0]['deadline'])
        self.assertTrue(any('预习' in item for item in candidates[0]['requirements']))
    def test_negated_and_already_completed_reading_are_not_new_tasks(self):
        for text in ['《阅读课》无需提前阅读材料，也不用准备讨论。',
                     '《阅读课》大家已经提前阅读了材料。',
                     '《阅读课》我昨天阅读了一篇文章，很有意思。']:
            self.assertEqual(parse_message(text,AT),[],text)
    def test_assignment_can_include_reading_besides_submission(self):
        candidate=parse_message('《英语》第一次作业：请提前阅读第二章，提交读书笔记。截止10月12日。',AT)[0]
        self.assertEqual(candidate['title'],'第一次作业')
        self.assertIn('读书笔记',candidate['requirements'])
        self.assertTrue(any('阅读' in item for item in candidate['requirements']))

    def test_reading_without_submission_stays_active_and_uses_class_deadline(self):
        task=parse_message('10-08 12:06\n《英语》请提前阅读第二章，无需提交。请在明天上课前完成。','2026-10-08T12:56:00+08:00')[0]
        self.assertEqual(task['operation'],'create')
        self.assertEqual(task['kind'],'other')
        self.assertEqual(task['deadline'],'2026-10-09')
    def test_multiple_reading_actions_preserve_books_and_chapters(self):
        task=parse_message('《英语》请阅读《动物农场》，并预习第二章。',AT)[0]
        self.assertIn('阅读《动物农场》',task['requirements'])
        self.assertIn('预习第二章',task['requirements'])
    def test_book_title_connective_is_not_cut_off(self):
        task=parse_message('《英语》请阅读《并发编程》，明天上课前完成。',AT)[0]
        self.assertIn('阅读《并发编程》',task['requirements'])
    def test_forbidden_or_postponed_submission_does_not_override_reading(self):
        for cue in ['请勿','暂不']:
            task=parse_message('10-08 12:06\n《英语》请提前阅读第二章，'+cue+'提交材料。请在明天上课前完成。','2026-10-08T12:56:00+08:00')[0]
            self.assertEqual(task['kind'],'other')
            self.assertEqual(task['operation'],'create')
            self.assertEqual(task['deadline'],'2026-10-09')
            self.assertEqual(task['requirements'],['阅读第二章'])
    def test_reading_date_before_deadline_cue_is_kept(self):
        task=parse_message('《英语》请提前阅读第二章，10月12日截止。',AT)[0]
        self.assertEqual(task['deadline'],'2026-10-12')
    def test_forbidden_or_postponed_reading_is_not_created(self):
        for text in ['《英语》请勿预习第二章。','《英语》请暂不阅读第一章。']:
            self.assertEqual(parse_message(text,AT),[],text)
    def test_standalone_discussion_preparation_creates_a_requirement(self):
        candidates=parse_message('《软件工程》请为第二次课的主题研讨做好准备，明天上课前完成。',AT)
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['kind'],'other')
        self.assertEqual(candidates[0]['deadline'],'2026-10-04')
        self.assertTrue(any('第二次课' in requirement and '研讨' in requirement for requirement in candidates[0]['requirements']))
    def test_presentation_and_submission_method_are_structured(self):
        candidate=parse_message('《软件工程》课程汇报：请于10月18日课堂展示，PPT上传至学习通。',AT)[0]
        self.assertEqual(candidate['kind'],'presentation')
        self.assertEqual(candidate['submission_method'],'课堂展示；学习通上传PPT')
        self.assertEqual(candidate['confidence'],'medium')
        self.assertIn('submission_method',candidate['field_evidence'])

class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'inbox.sqlite3'
        self.inbox = Inbox(self.path)
    def tearDown(self):
        self.temp.cleanup()
    def ingest(self, text=TEXT, scope='计科1班', at=AT, source='学习通', event_key=None):
        return self.inbox.ingest(text, source=source, captured_at=at, scope=scope, event_key=event_key)
    def create(self, **kwargs):
        r = self.ingest(**kwargs)
        return self.inbox.confirm(r['proposals'][0]['id'])
    def test_preclass_reanalysis_keeps_original_and_waits_for_confirmation(self):
        result=self.inbox.ingest(PRECLASS['text'],source='学习通',captured_at=PRECLASS['captured_at'],candidates=[])
        message_id=result['message']['id']
        refreshed=self.inbox.reanalyze(message_id)
        self.assertEqual(refreshed['message']['id'],message_id)
        self.assertEqual(refreshed['message']['text'],PRECLASS['text'])
        self.assertEqual(refreshed['message']['captured_at'],PRECLASS['captured_at'])
        self.assertEqual(len(refreshed['proposals']),1)
        self.assertEqual(self.inbox.tasks(),[])
        self.assertEqual(refreshed['proposals'][0]['candidate']['deadline'],'2026-10-09')

    def test_import_waits_for_confirmation(self):
        r = self.ingest()
        self.assertEqual(len(r['proposals']), 1)
        self.assertEqual(self.inbox.tasks(), [])
        self.assertEqual(r['mode'], 'rules')
    def test_rich_task_fields_persist_and_legacy_defaults_are_present(self):
        legacy=self.create()
        self.assertEqual(legacy['submission_method'],'')
        self.assertEqual(legacy['teacher'],'')
        candidate=parse_message(TEXT,AT,'软件工程','计科2班')[0]
        candidate.update(submission_method='学习通上传',teacher='王老师',source_url='https://mooc1.chaoxing.com/mooc-ans/work/view?workId=42',platform_status='未提交',confidence='high',field_evidence={'submission_method':'上传至学习通'})
        result=self.inbox.ingest(TEXT+'\n任务中心编号42',source='学习通网页 · 作业考试中心',captured_at=AT,scope='计科2班',candidates=[candidate])
        task=self.inbox.confirm(result['proposals'][0]['id'])
        self.assertEqual(task['submission_method'],'学习通上传')
        self.assertEqual(task['teacher'],'王老师')
        self.assertEqual(task['source_url'],'https://mooc1.chaoxing.com/mooc-ans/work/view?workId=42')
        self.assertEqual(task['platform_status'],'未提交')
        self.assertEqual(task['confidence'],'high')
        self.assertEqual(task['field_evidence'],{'submission_method':'上传至学习通'})
    def test_exact_replay_is_idempotent_and_confirmation_is_idempotent(self):
        first, replay = self.ingest(), self.ingest()
        self.assertEqual(first['message']['id'], replay['message']['id'])
        self.assertTrue(replay['duplicate'])
        a = self.inbox.confirm(first['proposals'][0]['id'])
        b = self.inbox.confirm(first['proposals'][0]['id'])
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(len(self.inbox.tasks()), 1)
    def test_duplicate_cross_source_links_evidence_not_second_task(self):
        t = self.create()
        r = self.ingest(source='班级群')
        self.assertEqual(r['proposals'][0]['action'], 'merge')
        result = self.inbox.confirm(r['proposals'][0]['id'])
        self.assertEqual(result['id'], t['id'])
        self.assertEqual(len(self.inbox.task_detail(t['id'])['sources']), 2)
    def test_merge_adds_complementary_requirements_without_overwriting(self):
        task=self.create()
        result=self.ingest('《软件工程》第三次作业：请提交实验报告、源代码、演示文稿。截止：2026年10月12日23:59。',source='课程通知')
        proposal=result['proposals'][0]
        self.assertEqual(proposal['action'],'merge')
        merged=self.inbox.confirm(proposal['id'])
        self.assertEqual([item['text'] for item in merged['checklist']],['实验报告','源代码','演示文稿'])
        self.assertEqual(merged['deadline'],task['deadline'])
    def test_older_merge_links_source_without_restoring_stale_requirements(self):
        current=self.create(at='2026-10-05T09:00:00+08:00')
        older=self.ingest('《软件工程》第三次作业：请提交实验报告、源代码、已废止材料。截止：2026年10月12日23:59。',source='较早群通知',at='2026-10-04T09:00:00+08:00')['proposals'][0]
        self.assertEqual(older['action'],'merge')
        result=self.inbox.confirm(older['id'])
        self.assertEqual([item['text'] for item in result['checklist']],['实验报告','源代码'])
        self.assertEqual(len(self.inbox.task_detail(current['id'])['sources']),2)
        self.assertEqual(self.inbox.task_detail(current['id'])['history'][0]['action'],'merge_older_source')
    def test_conflict_requires_explicit_resolution_and_records_both_choices(self):
        task=self.create()
        first=self.ingest('《软件工程》第三次作业：请提交实验报告、源代码。截止：2026年10月14日23:59。',source='课程群',at='2026-10-04T09:00:00+08:00')['proposals'][0]
        self.assertEqual(first['action'],'conflict')
        with self.assertRaisesRegex(ValidationError,'冲突'):
            self.inbox.confirm(first['id'])
        kept=self.inbox.confirm(first['id'],{'resolution':'current'})
        self.assertEqual(kept['deadline'],task['deadline'])
        self.assertEqual(self.inbox.task_detail(task['id'])['history'][0]['action'],'conflict_keep_current')
        second=self.ingest('《软件工程》第三次作业：请提交实验报告、源代码。截止：2026年10月15日23:59。',source='教师通知',at='2026-10-05T09:00:00+08:00')['proposals'][0]
        self.assertEqual(second['action'],'conflict')
        incoming=self.inbox.confirm(second['id'],{'resolution':'incoming'})
        self.assertEqual(incoming['deadline'],'2026-10-15T23:59:00+08:00')
        self.assertEqual(self.inbox.task_detail(task['id'])['history'][0]['action'],'conflict_use_incoming')
    def test_same_title_different_class_not_merged(self):
        self.create()
        r = self.ingest(scope='计科2班')
        self.assertEqual(r['proposals'][0]['action'], 'create')
        self.inbox.confirm(r['proposals'][0]['id'])
        self.assertEqual(len(self.inbox.tasks()), 2)
    def test_extension_stays_pending_then_records_history(self):
        t = self.create()
        r = self.ingest('《软件工程》 第三次作业延期到10月15日18:00。', at='2026-10-04T09:00:00+08:00')
        self.assertEqual(r['proposals'][0]['action'], 'update')
        self.assertEqual(self.inbox.task_detail(t['id'])['deadline'], '2026-10-12T23:59:00+08:00')
        changed = self.inbox.confirm(r['proposals'][0]['id'])
        self.assertEqual(changed['deadline'], '2026-10-15T18:00:00+08:00')
        detail = self.inbox.task_detail(t['id'])
        self.assertEqual(len(detail['history']), 2)
        self.assertEqual(detail['history'][0]['before']['deadline'], '2026-10-12T23:59:00+08:00')
    def test_stale_proposals_do_not_overwrite_newer_confirmation(self):
        t = self.create()
        a = self.ingest('《软件工程》 第三次作业延期到10月15日18:00。', at='2026-10-04T09:00:00+08:00')['proposals'][0]
        b = self.ingest('《软件工程》 第三次作业延期到10月16日18:00。', at='2026-10-05T09:00:00+08:00')['proposals'][0]
        self.inbox.confirm(b['id'])
        with self.assertRaises(Conflict):
            self.inbox.confirm(a['id'])
        self.assertEqual(self.inbox.task_detail(t['id'])['deadline'], '2026-10-16T18:00:00+08:00')
    def test_stale_extension_recovers_by_reanalysis_without_changing_message(self):
        t=self.create()
        original=self.ingest('《软件工程》 第三次作业延期到10月15日18:00。',at='2026-10-04T09:00:00+08:00')
        self.inbox.patch_task(t['id'],{'status':'in_progress'})
        p=original['proposals'][0]
        with self.assertRaises(Conflict): self.inbox.confirm(p['id'])
        self.inbox.dismiss(p['id'])
        rebuilt=self.inbox.reanalyze(original['message']['id'])
        self.assertEqual(rebuilt['message']['id'],original['message']['id'])
        self.assertEqual(rebuilt['message']['captured_at'],'2026-10-04T09:00:00+08:00')
        self.assertNotEqual(rebuilt['proposals'][0]['id'],p['id'])
        changed=self.inbox.confirm(rebuilt['proposals'][0]['id'])
        self.assertEqual(changed['deadline'],'2026-10-15T18:00:00+08:00')
        self.assertEqual(changed['status'],'in_progress')
        self.assertEqual(len(self.inbox.messages()),2)
    def test_merge_edits_do_not_bypass_older_message_protection(self):
        t=self.create()
        p=self.ingest(source='较早群通知',at='2026-10-02T09:00:00+08:00')['proposals'][0]
        self.assertEqual(p['action'],'merge')
        with self.assertRaises(Conflict):
            self.inbox.confirm(p['id'],{'deadline':'2026-10-10T18:00:00+08:00'})
        self.assertEqual(self.inbox.task_detail(t['id'])['deadline'],'2026-10-12T23:59:00+08:00')
    def test_edited_merge_is_recorded_as_actual_update(self):
        t=self.create()
        p=self.ingest(source='新群通知',at='2026-10-04T09:00:00+08:00')['proposals'][0]
        self.assertEqual(p['action'],'merge')
        self.inbox.confirm(p['id'],{'deadline':'2026-10-15T18:00:00+08:00'})
        history=self.inbox.task_detail(t['id'])['history'][0]
        self.assertEqual(history['action'],'update')
        self.assertEqual(history['after']['deadline'],'2026-10-15T18:00:00+08:00')
    def test_reanalysis_replaces_pending_drafts_and_keeps_old_records(self):
        original=self.ingest()
        refreshed=self.inbox.reanalyze(original['message']['id'])
        self.assertEqual(len(self.inbox.proposals()),1)
        self.assertEqual(len(self.inbox.proposals(None)),2)
        with self.assertRaises(Conflict): self.inbox.confirm(original['proposals'][0]['id'])
        self.inbox.confirm(refreshed['proposals'][0]['id'])
        self.assertEqual(len(self.inbox.tasks()),1)
    def test_cancel_requires_confirmation_and_scope_match(self):
        t = self.create()
        p = self.ingest('《软件工程》 第三次作业取消，不用提交。', at='2026-10-04T09:00:00+08:00')['proposals'][0]
        self.assertEqual(p['action'], 'cancel')
        self.assertEqual(self.inbox.task_detail(t['id'])['status'], 'pending')
        self.assertEqual(self.inbox.confirm(p['id'])['status'], 'cancelled')
    def test_done_is_not_submitted_and_remains_due(self):
        t = self.create()
        self.inbox.patch_task(t['id'], {'status':'done'})
        d = self.inbox.dashboard('2026-10-12T18:00:00+08:00')
        self.assertEqual(d['submitted'], 0)
        self.assertEqual(len(d['reminders']), 1)
        self.inbox.patch_task(t['id'], {'status':'submitted'})
        self.assertEqual(self.inbox.dashboard('2026-10-12T18:00:00+08:00')['reminders'], [])
    def test_data_persists_after_reopen(self):
        t = self.create()
        self.assertEqual(Inbox(self.path).task_detail(t['id'])['title'], '第三次作业')
    def test_ics_escapes_and_dates_are_timezone_correct(self):
        self.create()
        self.create(text='《高等数学》 第一次作业，10月13日前提交。')
        output = self.inbox.calendar()
        self.assertIn('DTSTART:20261012T155900Z', output)
        self.assertIn('DTSTART;VALUE=DATE:20261013', output)
        self.assertIn('BEGIN:VCALENDAR', output)
        self.assertEqual(output.count('BEGIN:VEVENT'), 2)
    def test_reject_invalid_status_and_deadline_edits(self):
        p = self.ingest()['proposals'][0]
        with self.assertRaises(ValidationError):
            self.inbox.confirm(p['id'], {'deadline':'随便一个时间'})
        t = self.inbox.confirm(p['id'])
        with self.assertRaises(ValidationError):
            self.inbox.patch_task(t['id'], {'status':'platform_confirmed'})

if __name__ == '__main__':
    unittest.main()
