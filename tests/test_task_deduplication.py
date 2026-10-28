import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox, Conflict, dump
from courseinbox.chaoxing import ingest_web_message


COURSE = '人工智能与深度学习'
TITLE = '目标检测编程实践'
AT = '2026-10-17T12:00:00+08:00'
DUE = '2026-10-30T23:59:00+08:00'


class TaskDeduplicationTests(unittest.TestCase):
    def test_explicit_merge_uses_full_original_chat_title_for_truncated_legacy_copy(self):
        primary=self.confirm(self.job(title='作业2：图像增强',deadline=DUE))
        message=self.box.ingest('作业2：图像增强',source='学习通网页 · 聊天正文',captured_at=AT,scope=COURSE,
            external=dict(platform='chaoxing-web',message_id='legacy-chat-message',direction='received'),candidates=[])['message']
        duplicate=dict(primary,id='legacy-chat',title='作业2',course='',source_url='',deadline=None,checklist=[],version=1)
        with self.box.connection() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?)',(duplicate['id'],'legacy-chat-key',dump(duplicate),1))
            db.execute('INSERT INTO sources VALUES(?,?)',(duplicate['id'],message['id']))
            db.execute('UPDATE messages SET data=? WHERE id=?',(dump(dict(message,text='作业2')),message['id']))
        with self.assertRaises(Conflict):
            self.box.merge_duplicate_tasks(primary['id'],duplicate['id'],{primary['id']:primary['version'],duplicate['id']:1})
        with self.box.connection() as db:
            db.execute('UPDATE messages SET data=? WHERE id=?',(dump(message),message['id']))
        merged=self.box.merge_duplicate_tasks(primary['id'],duplicate['id'],{primary['id']:primary['version'],duplicate['id']:1})
        self.assertEqual(merged['deadline'],DUE)
        self.assertEqual(len(self.box.tasks()),1)
        self.assertIn(message['id'],[m['id'] for m in self.box.task_detail(primary['id'])['sources']])

    def setUp(self):
        clock = patch('courseinbox.core.now_iso', return_value=AT)
        clock.start()
        self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.box = Inbox(Path(self.tmp.name) / 'inbox.sqlite3')

    def notice(self, number='1', course=COURSE, scope=None):
        return ingest_web_message(self.box, dict(kind='course_notice', message_id='notice_' + number,
            title='作业:《' + course + '》' + TITLE,
            text='课程名称：' + course + '\n作业名称：' + TITLE + '\n开始时间：2026-10-15 22:04\n结束时间：2026-10-30 23:59',
            course=course, conversation=scope or course, captured_at='2026-10-15T22:06:00+08:00',
            url='https://notice.chaoxing.com/pc/notice/notice-' + number + '/detail', attachments=[]))

    def job(self, number='42', title=TITLE, course=COURSE, group='2', deadline=None, suffix=''):
        return ingest_web_message(self.box, dict(kind='task_center', message_id='job_' + number + '_' + str(len(self.box.messages())),
            title=title, text=title + '；未交', course=course, conversation=course,
            captured_at=AT, url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=' + group + '&workId=' + number + suffix,
            platform_status='未交', deadline=deadline))

    def confirm(self, result):
        return self.box.confirm(result['proposals'][0]['id'])

    def legacy_pair(self):
        first = self.notice()
        primary = self.confirm(first)
        # Reproduce the old prefixed title and its old physical lookup key.
        primary['title'] = '作业:《' + COURSE + '》' + TITLE
        with self.box.connection() as db:
            db.execute('UPDATE tasks SET task_key=?,data=? WHERE id=?', ('legacy-notice', dump(dict(primary,title='旧存档占位')), primary['id']))
        # Seed two previously distinct records, then reproduce their legacy names.
        second = self.job()
        duplicate = self.confirm(second)
        with self.box.connection() as db:
            db.execute('UPDATE tasks SET data=? WHERE id=?',(dump(primary),primary['id']))
        return primary, duplicate, first, second

    def test_course_notice_uses_task_name_without_transport_prefix(self):
        proposal = self.notice()['proposals'][0]
        self.assertEqual(proposal['candidate']['title'], TITLE)
        self.assertEqual(proposal['candidate']['deadline'], DUE)

    def test_start_only_notice_has_no_invented_deadline_and_matches_task_center(self):
        result=ingest_web_message(self.box,dict(kind='course_notice',message_id='start_only',
            title='作业:《'+COURSE+'》作业1：BMP文件的读写',text='课程名称：'+COURSE+'\n作业名称：作业1：BMP文件的读写\n开始时间：2026-10-12 10:41',
            course=COURSE,conversation=COURSE,captured_at=AT,url='https://notice.chaoxing.com/pc/notice/start-only/detail'))
        self.assertIsNone(result['proposals'][0]['candidate']['deadline'])
        task=self.confirm(result)
        same=self.job(title='作业1：BMP文件的读写')
        self.assertEqual(self.confirm(same)['id'],task['id'])
        self.assertEqual(len(self.box.tasks()),1)

    def test_reviewed_legacy_merge_can_keep_primary_unknown_deadline(self):
        notice,job,_,_=self.legacy_pair()
        versions={t['id']:t['version'] for t in (notice,job)}
        merged=self.box.merge_duplicate_tasks(job['id'],notice['id'],versions,keep_primary_deadline=True)
        self.assertIsNone(merged['deadline'])
        self.assertEqual(merged['date_precision'],'unknown')
        self.assertEqual(len(self.box.task_detail(merged['id'])['sources']),2)
        history=self.box.task_detail(merged['id'])['history'][0]
        self.assertTrue(history['keep_primary_deadline'])
        self.assertEqual(history['merged_task']['deadline'],DUE)

    def test_notice_then_task_center_merges_sources_and_preserves_deadline(self):
        primary = self.confirm(self.notice())
        result = self.job()
        self.assertEqual(result['proposals'][0]['action'], 'merge')
        merged = self.confirm(result)
        self.assertEqual(merged['id'], primary['id'])
        self.assertEqual(merged['deadline'], DUE)
        self.assertIn('workId=42', merged['source_url'])
        self.assertEqual(len(self.box.tasks()), 1)
        self.assertEqual(len(self.box.task_detail(primary['id'])['sources']), 2)

    def test_older_notice_can_fill_unknown_deadline_after_human_confirmation(self):
        primary = self.confirm(self.job())
        result = self.notice()
        self.assertEqual(result['proposals'][0]['action'], 'merge')
        self.assertIsNone(self.box.task_detail(primary['id'])['deadline'])
        merged = self.confirm(result)
        self.assertEqual(merged['id'], primary['id'])
        self.assertEqual(merged['deadline'], DUE)
        self.assertEqual(merged['last_source_at'], AT)
        self.assertEqual(len(self.box.tasks()), 1)

    def test_legacy_prefixed_record_matches_without_mutating_it_during_ingest(self):
        primary = self.confirm(self.notice())
        primary['title'] = '作业:《' + COURSE + '》' + TITLE
        with self.box.connection() as db:
            db.execute('UPDATE tasks SET task_key=?,data=? WHERE id=?', ('legacy-title-key', dump(primary), primary['id']))
        result = self.job()
        self.assertEqual(result['proposals'][0]['target_id'], primary['id'])
        self.assertEqual(self.box.task_detail(primary['id'])['version'], primary['version'])
        self.assertEqual(self.confirm(result)['id'], primary['id'])

    def test_stable_platform_identity_ignores_link_signature_and_title_changes(self):
        primary = self.confirm(self.job(suffix='&enc=old-signature'))
        result = self.job(title='目标检测编程实践（补充说明）', suffix='&enc=new-signature')
        self.assertEqual(result['proposals'][0]['target_id'], primary['id'])
        self.assertEqual(self.confirm(result)['id'], primary['id'])
        self.assertEqual(len(self.box.tasks()), 1)

    def test_stable_id_precedes_display_labels_but_cannot_bypass_edit_guards(self):
        primary = self.confirm(self.job())
        result = ingest_web_message(self.box, dict(kind='task_center', message_id='renamed_display',
            title=TITLE, text='未交', course=COURSE, conversation='一班', captured_at=AT,
            url=primary['source_url']))
        proposal = result['proposals'][0]
        self.assertEqual(proposal['target_id'], primary['id'])
        with self.assertRaises(Conflict):
            self.box.confirm(proposal['id'], {'course': '其他课程'})
        self.assertEqual(self.confirm(result)['id'], primary['id'])
        self.assertEqual(len(self.box.tasks()), 1)

    def test_repeated_signature_parameters_cannot_erase_distinct_platform_ids(self):
        primary = self.confirm(self.job(number='43'))
        result = self.job(number='42', suffix='&enc=a&enc=b')
        self.assertIsNone(result['proposals'][0]['target_id'])
        self.assertNotEqual(self.confirm(result)['id'], primary['id'])

    def test_older_task_center_source_fills_identity_without_losing_newer_deadline(self):
        primary = self.confirm(self.notice())
        result = self.job()
        # Platform scan arrived later, but carries an earlier source timestamp.
        with self.box.connection() as db:
            row = db.execute('SELECT data FROM messages WHERE id=?', (result['message']['id'],)).fetchone()
            message = json.loads(row[0]);message['captured_at']='2026-10-14T10:00:00+08:00'
            db.execute('UPDATE messages SET data=? WHERE id=?', (dump(message), message['id']))
        merged = self.confirm(result)
        self.assertIn('workId=42', merged['source_url'])
        self.assertEqual(merged['deadline'], DUE)
        self.assertIsNone(self.job(number='43')['proposals'][0]['target_id'])
        # An old database may already retain that source without a preferred URL.
        merged['source_url']=''
        with self.box.connection() as db:
            db.execute('UPDATE tasks SET data=? WHERE id=?', (dump(merged), primary['id']))
        self.assertIsNone(self.job(number='44')['proposals'][0]['target_id'])

    def test_distinct_platform_ids_and_classes_do_not_merge_same_title(self):
        self.confirm(self.job())
        second = self.job(number='43')
        self.assertIsNone(second['proposals'][0]['target_id'])
        self.confirm(second)
        third = self.job(group='3')
        self.assertIsNone(third['proposals'][0]['target_id'])
        self.confirm(third)
        self.assertEqual(len(self.box.tasks()), 3)

    def test_ambiguous_notice_cannot_create_third_copy_or_choose_wrong_platform_id(self):
        self.confirm(self.job())
        self.confirm(self.job(number='43'))
        result = self.notice()
        with self.assertRaisesRegex(Conflict, '多个|同名'):
            self.confirm(result)
        self.assertEqual(len(self.box.tasks()), 2)

    def test_other_course_and_class_notice_remain_separate(self):
        self.confirm(self.notice(scope='一班'))
        for result in (self.notice('2', course='计算机视觉'), self.notice('3', scope='二班')):
            self.assertIsNone(result['proposals'][0]['target_id'])
            self.confirm(result)
        self.assertEqual(len(self.box.tasks()), 3)

    def test_assignment_numbers_and_exam_namespace_remain_distinct(self):
        self.confirm(self.job(title='作业1：BMP文件的读写'))
        other = self.job(number='43', title='作业2：BMP文件的读写')
        self.assertIsNone(other['proposals'][0]['target_id'])
        self.confirm(other)
        assignment = self.confirm(self.job(number='44'))
        exam = ingest_web_message(self.box, dict(kind='task_center', message_id='exam_44', title=TITLE,
            text='请参加考试', course=COURSE, conversation=COURSE, captured_at=AT, task_type='exam',
            url='https://mooc1.chaoxing.com/exam-ans/exam/view?courseId=1&classId=2&examId=44'))
        self.assertIsNone(exam['proposals'][0]['target_id'])
        self.assertNotEqual(self.confirm(exam)['id'], assignment['id'])
        self.assertEqual(len(self.box.tasks()), 4)

    def test_merge_legacy_pair_preserves_evidence_audit_and_old_task_links(self):
        primary, duplicate, first, second = self.legacy_pair()
        self.assertEqual(len(self.box.tasks()), 2)
        versions = {task['id']: task['version'] for task in (primary, duplicate)}
        merged = self.box.merge_duplicate_tasks(primary['id'], duplicate['id'], versions)
        self.assertEqual(merged['id'], primary['id'])
        self.assertEqual(merged['title'], TITLE)
        self.assertEqual(merged['deadline'], DUE)
        self.assertIn('workId=42', merged['source_url'])
        self.assertEqual(len(self.box.tasks()), 1)
        detail = self.box.task_detail(duplicate['id'])
        self.assertEqual(detail['id'], primary['id'])
        self.assertEqual({message['id'] for message in detail['sources']}, {first['message']['id'], second['message']['id']})
        self.assertEqual(detail['history'][0]['action'], 'duplicate_task_merged')
        self.assertEqual(detail['history'][0]['merged_task']['id'], duplicate['id'])
        self.assertEqual(self.box.confirm(second['proposals'][0]['id'])['id'], primary['id'])
        with self.box.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 2)
            self.assertEqual(json.loads(db.execute('SELECT data FROM tasks WHERE id=?', (duplicate['id'],)).fetchone()[0])['merged_into'], primary['id'])
        self.assertEqual(self.box.merge_duplicate_tasks(primary['id'], duplicate['id'], versions)['version'], merged['version'])
        reopened = Inbox(self.box.path)
        self.assertEqual(len(reopened.tasks()), 1)
        self.assertEqual(reopened.task_detail(duplicate['id'])['id'], primary['id'])
        self.assertEqual(reopened.dashboard()['total'], 1)
        self.assertEqual(reopened.calendar().count('BEGIN:VEVENT'), 1)

    def test_merge_refuses_stale_versions_and_conflicting_deadlines_or_status(self):
        primary, duplicate, _, _ = self.legacy_pair()
        versions = {task['id']: task['version'] for task in (primary, duplicate)}
        with self.assertRaises(Conflict):
            self.box.merge_duplicate_tasks(primary['id'], duplicate['id'], {**versions, primary['id']: 99})
        for changes in ({'deadline': '2026-11-01'}, {'status': 'submitted'}):
            with self.subTest(changes=changes):
                altered = dict(duplicate, **changes)
                with self.box.connection() as db:
                    db.execute('UPDATE tasks SET data=? WHERE id=?', (dump(altered), duplicate['id']))
                with self.assertRaises(Conflict):
                    self.box.merge_duplicate_tasks(primary['id'], duplicate['id'], versions)
                self.assertEqual(len(self.box.tasks()), 2)

    def test_merge_refuses_distinct_platform_tasks(self):
        primary = self.confirm(self.job())
        duplicate = self.confirm(self.job(number='43'))
        versions = {task['id']: task['version'] for task in (primary, duplicate)}
        with self.assertRaises(Conflict):
            self.box.merge_duplicate_tasks(primary['id'], duplicate['id'], versions)
        self.assertEqual(len(self.box.tasks()), 2)


if __name__ == '__main__':
    unittest.main()
