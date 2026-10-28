import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox, Conflict, ValidationError, dump, task_key
from courseinbox.chaoxing import ingest_web_message


URL = 'https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42'
AT = '2026-10-17T12:00:00+08:00'


class IdentityInvariantTests(unittest.TestCase):
    def test_concurrent_number_alias_confirmations_create_only_one_task(self):
        a=self.capture(title='作业2：图像增强',course='数字图像处理',scope='数字图像处理',url=URL)
        b=self.capture(title='第二次作业',course='',scope='数字图像处理',matchable=False,deadline=None)
        other=Inbox(self.path);barrier=threading.Barrier(2)
        def confirm(box,result):
            barrier.wait()
            try:return box.confirm(result['proposals'][0]['id'])['id']
            except Conflict:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(confirm,self.box,a),pool.submit(confirm,other,b)]
            self.assertEqual(sum(job.result(timeout=10) is not None for job in jobs),1)
        self.assertEqual(len(self.box.tasks()),1)

    def test_number_aliases_never_join_other_ids_courses_classes_or_numbers(self):
        from courseinbox.task_identity import possible_duplicate
        base=dict(title='作业2：图像增强',course='数字图像处理',scope='一班',kind='assignment',source_url=URL)
        for changes in (dict(title='作业三'),dict(title='第二十次作业'),dict(course='其他课程'),dict(scope='二班'),dict(source_url=URL.replace('workId=42','workId=43'))):
            with self.subTest(changes=changes):
                candidate=dict(base,title='第二次作业',source_url='')
                candidate.update(changes)
                if 'title' in changes:candidate['title']=changes['title']
                self.assertFalse(possible_duplicate(candidate,base))

    def test_number_aliases_are_review_only(self):
        task=self.confirm(self.capture(title='作业2：图像增强',course='数字图像处理',scope='数字图像处理',url=URL))
        for title in ('作业二','第二次作业','第2次作业：图像增强','作业：第二次作业','作业：《数字图像处理》作业二：图像增强'):
            with self.subTest(title=title):
                incoming=self.capture(title=title,course='',scope='数字图像处理',matchable=False,deadline=None)
                self.assertIsNone(incoming['proposals'][0]['target_id'])
                self.assertIn(task['id'],[r['task_id'] for r in incoming['proposals'][0]['duplicate_review']])
                with self.assertRaises(Conflict):self.confirm(incoming)

    def test_old_pending_view_refreshes_duplicate_checks_after_task_creation(self):
        old=self.capture(title='作业2',course='',scope='数字图像处理',matchable=False,deadline=None)
        self.assertEqual(old['proposals'][0]['duplicate_review'],[])
        task=self.confirm(self.capture(title='作业2：图像增强',course='数字图像处理',scope='数字图像处理',url=URL))
        pending=next(p for p in self.box.proposals() if p['id']==old['proposals'][0]['id'])
        self.assertIn(task['id'],[r['task_id'] for r in pending['duplicate_review']])
        with self.assertRaises(Conflict):self.confirm(old)

    def test_number_only_chat_title_requires_duplicate_review(self):
        task=self.confirm(self.capture(title='作业2：图像增强',course='数字图像处理',scope='数字图像处理',url=URL))
        incoming=self.capture(title='作业2',course='',scope='数字图像处理',matchable=False,deadline=None)
        proposal=incoming['proposals'][0]
        self.assertIn(task['id'],[item['task_id'] for item in proposal['duplicate_review']])
        with self.assertRaises(Conflict):self.confirm(incoming)

    def test_number_only_title_does_not_review_other_course_or_number(self):
        self.confirm(self.capture(title='作业2：图像增强',course='数字图像处理',scope='数字图像处理',url=URL))
        for title,scope in [('作业1','数字图像处理'),('作业2','其他课程'),('作业20','数字图像处理')]:
            incoming=self.capture(title=title,course='',scope=scope,matchable=False,deadline=None)
            self.assertEqual(incoming['proposals'][0]['duplicate_review'],[])

    def setUp(self):
        clock = patch('courseinbox.core.now_iso', return_value=AT)
        clock.start();self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'inbox.sqlite3'
        self.box = Inbox(self.path);self.sequence = 0

    def capture(self, title='目标检测编程实践', course='人工智能', scope='一班', url='', matchable=True, deadline='2030-10-30', source='学习通课程通知', kind='assignment', at=AT, operation='create'):
        self.sequence += 1
        text = '课程作业：' + title + '\n请提交实验报告。'
        candidate = dict(title=title, course=course, scope=scope, kind=kind, operation=operation,
            deadline=deadline, requirements=['实验报告'], matchable=matchable, source_url=url, evidence=text)
        return self.box.ingest(text, source=source, captured_at=at, course=course, scope=scope,
            event_key=str(self.sequence), candidates=[candidate])

    def confirm(self, result, box=None):
        return (box or self.box).confirm(result['proposals'][0]['id'])

    def test_complete_platform_key_is_independent_of_labels_and_matchable_flag(self):
        first = dict(course='人工智能', scope='一班', title='目标检测', source_url=URL, matchable=False)
        second = dict(first, course='课程新显示名', scope='课程名', title='新版名称', matchable=True)
        self.assertIsNotNone(task_key(first))
        self.assertEqual(task_key(first), task_key(second))

    def test_full_identity_cannot_be_bypassed_by_unmatchable_candidate(self):
        task = self.confirm(self.capture(url=URL, matchable=False))
        second = self.capture(url=URL + '&enc=changed', matchable=False, title='新版任务名', scope='课程名')
        self.assertEqual(second['proposals'][0]['target_id'], task['id'])
        self.assertEqual(self.confirm(second)['id'], task['id'])
        self.assertEqual(len(self.box.tasks()), 1)

    def test_registry_has_database_unique_constraint_and_survives_restart(self):
        task = self.confirm(self.capture(url=URL))
        with self.box.connection() as db:
            claim = db.execute('SELECT identity,task_id FROM task_identities').fetchone()
            self.assertEqual(claim['task_id'], task['id'])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO task_identities VALUES(?,?)', (claim['identity'], 'another-task'))
        reopened = Inbox(self.path)
        self.assertEqual(reopened.task_detail(task['id'])['id'], task['id'])
        with reopened.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM task_identities').fetchone()[0], 1)

    def test_concurrent_inbox_instances_cannot_confirm_same_platform_task_twice(self):
        first = self.capture(url=URL, matchable=False)
        # Distinct fields leave two versions for review rather than one equivalent draft.
        second = self.capture(url=URL, matchable=False, scope='课程名', deadline='2030-11-01')
        other = Inbox(self.path);barrier = threading.Barrier(2)
        def run(box, proposal):
            barrier.wait()
            try:return box.confirm(proposal['proposals'][0]['id'])['id']
            except Conflict:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run, self.box, first), pool.submit(run, other, second)]
            results = [job.result(timeout=10) for job in jobs]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.box.tasks()), 1)

    def test_equivalent_pending_sources_share_one_draft_and_all_evidence(self):
        first = self.capture(url=URL)
        second = self.capture(url=URL + '&enc=new', scope='课程显示名称', source='学习通作业中心')
        self.assertEqual(first['proposals'][0]['id'], second['proposals'][0]['id'])
        self.assertEqual(len(self.box.proposals()), 1)
        self.box.clear_messages([second['message']['id']])
        task = self.confirm(first)
        self.assertEqual({m['id'] for m in self.box.task_detail(task['id'])['sources']}, {first['message']['id'], second['message']['id']})
        self.assertEqual(len(self.box.tasks()), 1)

    def test_pending_distinct_platform_ids_stay_separate_even_with_same_name(self):
        first = self.capture(url=URL)
        second = self.capture(url=URL.replace('workId=42', 'workId=43'))
        self.assertNotEqual(first['proposals'][0]['id'], second['proposals'][0]['id'])
        self.confirm(first);self.confirm(second)
        self.assertEqual(len(self.box.tasks()), 2)

    def test_materially_different_pending_versions_are_not_silently_folded(self):
        first = self.capture(url=URL)
        second = self.capture(url=URL, deadline='2030-11-01')
        self.assertNotEqual(first['proposals'][0]['id'], second['proposals'][0]['id'])
        self.confirm(first)
        with self.assertRaises(Conflict):self.confirm(second)
        self.assertEqual(len(self.box.tasks()), 1)

    def test_pending_source_group_cannot_absorb_another_platform_id(self):
        notice = self.capture()
        job = self.capture(url=URL, source='学习通作业中心')
        self.assertEqual(notice['proposals'][0]['id'], job['proposals'][0]['id'])
        other = self.capture(url=URL.replace('workId=42', 'workId=43'))
        self.assertNotEqual(other['proposals'][0]['id'], notice['proposals'][0]['id'])
        first = self.confirm(notice)
        self.assertIsNone(other['proposals'][0]['target_id'])
        self.assertNotEqual(self.confirm(other)['id'], first['id'])

    def test_similar_unidentified_task_is_held_instead_of_created_or_auto_merged(self):
        self.confirm(self.capture())
        possible = self.capture(title='目标检测编程实践（作业）')
        self.assertTrue(possible['proposals'][0].get('duplicate_review'))
        with self.assertRaisesRegex(Conflict, '疑似重复|核对'):
            self.confirm(possible)
        self.assertEqual(len(self.box.tasks()), 1)
        self.assertEqual(len(self.box.messages()), 2)

    def test_changed_display_scope_without_id_is_held_for_review(self):
        self.confirm(self.capture())
        possible = self.capture(scope='人工智能')
        self.assertTrue(possible['proposals'][0].get('duplicate_review'))
        with self.assertRaises(Conflict):self.confirm(possible)

    def test_explicit_review_links_only_source_with_version_guard(self):
        task = self.confirm(self.capture())
        possible = self.capture(title='目标检测编程实践（作业）', deadline='2030-11-01')
        proposal = possible['proposals'][0]
        with self.assertRaises(Conflict):
            self.box.confirm(proposal['id'], dict(link_only_to=task['id'], expected_version=99))
        linked = self.box.confirm(proposal['id'], dict(link_only_to=task['id'], expected_version=task['version']))
        self.assertEqual(linked['id'], task['id'])
        self.assertEqual(linked['deadline'], task['deadline'])
        self.assertEqual(linked['status'], task['status'])
        self.assertEqual(len(self.box.tasks()), 1)
        self.assertEqual(len(self.box.task_detail(task['id'])['sources']), 2)
        self.assertEqual(self.box.task_detail(task['id'])['history'][0]['action'], 'duplicate_source_linked')

    def test_weak_matchable_flag_cannot_create_copy_of_existing_named_task(self):
        self.confirm(self.capture())
        possible = self.capture(matchable=False)
        with self.assertRaises(Conflict):self.confirm(possible)
        self.assertEqual(len(self.box.tasks()), 1)

    def test_task_with_conflicting_linked_identities_is_held_for_review(self):
        task = self.confirm(self.capture(url=URL))
        extra = self.box.ingest('历史来源', captured_at=AT, candidates=[], external=dict(platform='chaoxing-web', kind='task_center', message_id='legacy-conflict', url=URL.replace('workId=42','workId=43')))
        with self.box.connection() as db:
            db.execute('INSERT INTO sources VALUES(?,?)', (task['id'], extra['message']['id']))
        possible = self.capture(url=URL.replace('workId=42', 'workId=43'), deadline='2030-11-01')
        self.assertTrue(possible['proposals'][0].get('duplicate_review'))
        with self.assertRaises(Conflict):self.confirm(possible)

    def test_conflicting_identity_aliases_save_raw_source_without_task(self):
        for suffix in ('&clazzId=3', '&course_id=99', '&work_id=43', '&examId=42', '&id=43'):
            with self.subTest(suffix=suffix):
                self.sequence += 1
                result = ingest_web_message(self.box, dict(kind='task_center', message_id='invalid_' + str(self.sequence),
                    title='目标检测编程实践', text='请提交实验报告', course='人工智能', conversation='一班',
                    captured_at=AT, url=URL + suffix, deadline='2030-10-30'))
                self.assertEqual(result['proposals'], [])
                self.assertTrue(result['message']['text'])
        self.assertEqual(self.box.tasks(), [])

    def test_incomplete_exam_link_cannot_create_copy_of_existing_exam(self):
        url=URL.replace('/work/', '/exam/').replace('workId=42', 'examId=42')
        task=self.confirm(self.capture(url=url, kind='exam'))
        same=self.capture(url=url.replace('&examId=42',''), kind='exam')
        self.assertEqual(same['proposals'][0]['target_id'],task['id'])
        self.assertEqual(self.confirm(same)['id'],task['id'])
        self.assertEqual(len(self.box.tasks()),1)

    def test_pending_partial_id_conflicts_stay_separate(self):
        first=self.capture(url=URL)
        other=self.capture(url=URL.replace('classId=2&workId=42','classId=3'))
        self.assertNotEqual(first['proposals'][0]['id'],other['proposals'][0]['id'])
        self.assertEqual(first['proposals'][0]['source_count'],1)

    def test_reanalyze_either_shared_source_retains_group_identity_and_all_evidence(self):
        text='任务名称：目标检测编程实践\n请提交实验报告。'
        for index in (0,1):
            with self.subTest(primary=index==0):
                box=Inbox(Path(self.tmp.name)/('group-'+str(index)+'.sqlite3'))
                first=box.ingest(text,course='人工智能',scope='一班',captured_at=AT,event_key='first')
                candidate=dict(first['proposals'][0]['candidate'],source_url=URL)
                second=box.ingest(text,course='人工智能',scope='一班',captured_at=AT,event_key='second',candidates=[candidate])
                self.assertEqual(first['proposals'][0]['id'],second['proposals'][0]['id'])
                rebuilt=box.reanalyze((first,second)[index]['message']['id'])
                self.assertEqual(len(box.proposals()),1)
                self.assertEqual(rebuilt['proposals'][0]['source_count'],2)
                task=box.confirm(rebuilt['proposals'][0]['id'])
                self.assertEqual(len(box.task_detail(task['id'])['sources']),2)
                self.assertEqual(task['source_url'],URL)
                replay=box.ingest(text,course='人工智能',scope='一班',captured_at=AT,event_key='second')
                self.assertIn(rebuilt['proposals'][0]['id'],[p['id'] for p in replay['proposals']])

    def test_reanalyze_task_center_keeps_structured_platform_identity(self):
        result=ingest_web_message(self.box,dict(kind='task_center',message_id='structured',title='目标检测编程实践',
            text='请提交实验报告',course='人工智能',conversation='一班',captured_at=AT,url=URL,deadline='2030-10-30'))
        rebuilt=self.box.reanalyze(result['message']['id'])
        task=self.confirm(rebuilt)
        self.assertEqual(task['source_url'],URL)
        self.assertEqual(task['title'],'目标检测编程实践')
        self.assertEqual(task['deadline'],'2030-10-30')

    def test_attachment_enrichment_retains_shared_sources(self):
        payload=dict(kind='course_notice',message_id='enrichment',title='任务名称：目标检测编程实践',text='请提交实验报告。',
            course='人工智能',conversation='一班',captured_at=AT,url='https://notice.chaoxing.com/pc/notice/enrichment/detail',
            attachments=[dict(name='要求.docx',url='',status='failed',text='',error='暂时读取失败')])
        first=ingest_web_message(self.box,payload)
        second=self.box.ingest(first['message']['text'],course='人工智能',scope='一班',captured_at=AT,
            candidates=[dict(first['proposals'][0]['candidate'],source_url=URL)])
        self.assertEqual(first['proposals'][0]['id'],second['proposals'][0]['id'])
        payload['attachments'][0].update(status='extracted',text='请提交实验报告总结。',error='')
        rebuilt=ingest_web_message(self.box,payload)
        self.assertTrue(rebuilt['enriched'])
        self.assertEqual(len(self.box.proposals()),1)
        self.assertEqual(rebuilt['proposals'][0]['source_count'],2)
        task=self.confirm(rebuilt)
        self.assertEqual(len(self.box.task_detail(task['id'])['sources']),2)
        self.assertEqual(task['source_url'],URL)

    def test_newer_equivalent_update_supersedes_old_primary_and_replay_keeps_group(self):
        task=self.confirm(self.capture(url=URL,at='2026-10-17T11:00:00+08:00'))
        old=self.capture(url=URL,at='2026-10-17T10:00:00+08:00',operation='update',deadline='2030-11-01')
        new=self.capture(url=URL,at=AT,operation='update',deadline='2030-11-01')
        self.assertEqual(old['proposals'][0]['id'],new['proposals'][0]['id'])
        updated=self.confirm(new)
        self.assertEqual(updated['id'],task['id'])
        self.assertEqual(updated['last_source_at'],AT)
        self.assertEqual(updated['deadline'],'2030-11-01')
        self.assertEqual(len(self.box.task_detail(task['id'])['sources']),3)
        self.sequence-=1
        replay=self.capture(url=URL,at='2026-10-17T10:00:00+08:00',operation='update',deadline='2030-11-01')
        self.assertTrue(replay['duplicate'])
        self.assertIn(new['proposals'][0]['id'],[p['id'] for p in replay['proposals']])

    def test_reanalyze_older_member_keeps_latest_equivalent_update_authority(self):
        task=self.confirm(self.capture(url=URL,at='2026-10-17T11:00:00+08:00'))
        text='任务名称：目标检测编程实践\n原截止2030年10月30日，现延期到2030年11月1日。请提交实验报告。'
        old=self.box.ingest(text,course='人工智能',scope='一班',captured_at='2026-10-17T10:00:00+08:00',event_key='old')
        new=self.box.ingest(text,course='人工智能',scope='一班',captured_at=AT,event_key='new')
        self.assertEqual(old['proposals'][0]['id'],new['proposals'][0]['id'])
        rebuilt=self.box.reanalyze(old['message']['id'])
        self.assertEqual(rebuilt['proposals'][0]['message_id'],new['message']['id'])
        updated=self.confirm(rebuilt)
        self.assertEqual(updated['id'],task['id'])
        self.assertEqual(updated['last_source_at'],AT)
        self.assertEqual(updated['deadline'],'2030-11-01')
        self.assertEqual(len(self.box.task_detail(task['id'])['sources']),3)

    def test_unicode_equivalent_transport_titles_match_without_changing_numbers(self):
        task = self.confirm(self.capture(title='实验１：目标检测', url=''))
        same = self.capture(title='实验1：目标\u200b检测', source='另一来源')
        self.assertEqual(same['proposals'][0]['target_id'], task['id'])
        other = self.capture(title='实验2：目标检测')
        self.assertIsNone(other['proposals'][0]['target_id'])
        self.confirm(other)
        self.assertEqual(len(self.box.tasks()), 2)


if __name__ == '__main__':
    unittest.main()
