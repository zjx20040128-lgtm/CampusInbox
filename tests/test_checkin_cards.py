import unittest
import tempfile
from pathlib import Path
from courseinbox.core import Inbox, parse_message
from courseinbox.chaoxing import ingest_web_message


class CheckinCardTests(unittest.TestCase):
    def test_activity_update_view_and_refresh_keep_original_target(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox=Inbox(Path(directory)/'test.sqlite3')
            chat=ingest_web_message(inbox,dict(message_id='chat-sign',text='位置签到',conversation='示例课程',captured_at='2026-10-20T13:12:00+08:00',direction='received'))
            # Seed a legacy task created before mandatory activity verification.
            from unittest.mock import patch
            with patch('courseinbox.checkin_evidence.verification',return_value='verified'):
                task=inbox.confirm(chat['proposals'][0]['id'])
            result=ingest_web_message(inbox,dict(kind='checkin_activity',message_id='checkin-1',text='位置签到',title='位置签到',conversation='示例课程',captured_at='2026-10-20T13:12:31+08:00',published_at='2026-10-20T13:12:31+08:00',deadline='2026-10-20T13:42:31+08:00',activity_id='123',course_id='456',class_id='789',field_evidence={'deadline':'学习通签到活动结束时间：2026-10-20 13:42:31'}))
            proposal=result['proposals'][0]
            view=next(p for p in inbox.proposals() if p['id']==proposal['id'])
            self.assertEqual(view['duplicate_review'],[])
            from courseinbox.core import Conflict,dump
            with inbox.connection() as db:
                changed=dict(result['message'],external=dict(result['message']['external'],chat_source_id='unrelated'))
                db.execute('UPDATE messages SET data=? WHERE id=?',(dump(changed),changed['id']))
            self.assertTrue(next(p for p in inbox.proposals() if p['id']==proposal['id'])['duplicate_review'])
            with self.assertRaises(Conflict):inbox.confirm(proposal['id'])
            with inbox.connection() as db:
                db.execute('UPDATE messages SET data=? WHERE id=?',(dump(result['message']),changed['id']))
            inbox.patch_task(task['id'],{'status':'in_progress','expected_version':task['version']})
            with self.assertRaises(Conflict):inbox.confirm(proposal['id'])
            refreshed=inbox.reanalyze(result['message']['id'])['proposals'][0]
            self.assertEqual(refreshed['target_id'],task['id'])
            self.assertEqual(refreshed['expected_version'],2)
            updated=inbox.confirm(refreshed['id'])
            self.assertEqual(updated['deadline'],'2026-10-20T13:42:31+08:00')
            self.assertEqual(updated['status'],'in_progress')
            self.assertEqual(len(inbox.tasks()),1)

    def test_card_title_and_kind_without_inventing_deadline(self):
        for title in ('签到码签到', '二维码签到', '位置签到', '手势签到', '普通签到'):
            with self.subTest(title=title):
                candidate = parse_message(title, '2026-10-25T14:24:00+08:00', scope='测试')[0]
                self.assertEqual(candidate['title'], title)
                self.assertEqual(candidate['kind'], 'other')
                self.assertIsNone(candidate['deadline'])
                self.assertEqual(candidate['course'], '')
                self.assertEqual(candidate['scope'], '测试')

    def test_web_intake_saves_original_and_reviewable_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory) / 'test.sqlite3')
            body = dict(message_id='checkin-card', text='签到码签到', conversation='测试',
                        sender='老师', display_time='10-25 14:24', captured_at='2026-10-25T14:24:00+08:00', direction='received')
            result = ingest_web_message(inbox, body)
            self.assertEqual(len(result['proposals']), 1)
            self.assertEqual(result['proposals'][0]['candidate']['title'], '签到码签到')
            self.assertIsNone(result['proposals'][0]['candidate']['deadline'])
            repeated = ingest_web_message(inbox, body)
            self.assertTrue(repeated['duplicate'])
