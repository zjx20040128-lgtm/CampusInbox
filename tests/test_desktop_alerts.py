import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox
from courseinbox.desktop_alerts import DesktopAlerts


class DesktopAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'inbox.sqlite3'
        self.box = Inbox(self.path)
        self.alerts = DesktopAlerts(self.box)

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, text, at, source='学习通课程通知'):
        with patch('courseinbox.core.now_iso', return_value=at):
            return self.box.ingest(text, source=source, captured_at=at)

    def test_first_run_seeds_existing_backlog_then_new_message_and_ack_persist(self):
        self.ingest('《数学》第一次作业，请完成报告。', '2026-10-15T12:00:00+08:00')
        self.assertEqual(self.alerts.poll('2026-10-16T12:00:00+08:00')['events'], [])
        result = self.ingest('《数学》第二次作业，请完成报告。', '2026-10-16T12:01:00+08:00')
        events = self.alerts.poll('2026-10-16T12:02:00+08:00')['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'new_pending')
        self.assertEqual(events[0]['url'], '/?message='+result['message']['id']+'#inbox')
        self.alerts.ack([events[0]['id']])
        self.assertEqual(DesktopAlerts(Inbox(self.path)).poll('2026-10-16T12:03:00+08:00')['events'], [])

    def test_late_backfill_does_not_become_new_message_alert(self):
        self.alerts.poll('2026-10-16T12:00:00+08:00')
        self.ingest('《数学》历史作业，请于2026年10月30日提交报告。', '2025-03-09T12:00:00+08:00')
        self.assertEqual(self.alerts.poll('2026-10-16T12:02:00+08:00')['events'], [])

    def test_thresholds_change_and_submitted_tasks_stop_alerts(self):
        self.alerts.poll('2026-10-16T08:00:00+08:00')
        result = self.ingest('《数学》第一次作业，请于2026年10月16日18:00前提交报告。', '2026-10-16T09:00:00+08:00', source='手动导入')
        task = self.box.confirm(result['proposals'][0]['id'])
        today = self.alerts.poll('2026-10-16T10:00:00+08:00')['events']
        self.assertEqual(len(today), 1)
        self.alerts.ack([today[0]['id']])
        soon = self.alerts.poll('2026-10-16T17:00:00+08:00')['events']
        self.assertEqual(len(soon), 1)
        self.assertNotEqual(soon[0]['id'], today[0]['id'])
        self.box.patch_task(task['id'], dict(status='submitted',expected_version=task['version']))
        self.assertEqual(self.alerts.poll('2026-10-16T19:00:00+08:00')['events'], [])

    def test_date_only_reminder_does_not_invent_midnight_deadline(self):
        self.alerts.poll('2026-10-15T08:00:00+08:00')
        result = self.ingest('《数学》第一次作业，截止2026年10月16日，请提交报告。', '2026-10-15T08:01:00+08:00', source='手动导入')
        self.box.confirm(result['proposals'][0]['id'])
        self.assertEqual(self.alerts.poll('2026-10-15T08:30:00+08:00')['events'], [])
        events = self.alerts.poll('2026-10-15T09:00:00+08:00')['events']
        self.assertEqual(len(events), 1)
        self.assertIn('时刻未明确', events[0]['body'])
        self.assertNotIn('00:00', events[0]['body'])

    def test_deadline_change_is_reviewable_and_reschedules_confirmed_reminder(self):
        self.alerts.poll('2026-10-16T08:00:00+08:00')
        original=self.ingest('《数学》第一次作业，截止2026年10月16日18:00，请提交报告。','2026-10-16T09:00:00+08:00',source='手动导入')
        task=self.box.confirm(original['proposals'][0]['id'])
        prior=self.alerts.poll('2026-10-16T10:00:00+08:00')['events']
        self.alerts.ack([event['id'] for event in prior])
        changed=self.ingest('《数学》第一次作业延期到2026年10月17日18:00，其他要求不变。','2026-10-16T12:00:00+08:00')
        pending=self.alerts.poll('2026-10-16T12:01:00+08:00')['events']
        self.assertEqual([event['kind'] for event in pending],['deadline_change'])
        self.assertEqual(self.box.task_detail(task['id'])['deadline'],'2026-10-16T18:00:00+08:00')
        self.alerts.ack([event['id'] for event in pending])
        updated=self.box.confirm(changed['proposals'][0]['id'])
        next_events=self.alerts.poll('2026-10-16T19:00:00+08:00')['events']
        self.assertEqual([event['kind'] for event in next_events],['deadline_due'])
        self.assertNotEqual(next_events[0]['id'],prior[0]['id'])
        self.box.patch_task(updated['id'],dict(status='cancelled',expected_version=updated['version']))
        self.assertEqual(self.alerts.poll('2026-10-17T19:00:00+08:00')['events'],[])

    def test_disable_and_enable_skip_backlog_and_respect_cleanup(self):
        self.alerts.poll('2026-10-16T12:00:00+08:00')
        self.alerts.settings(False, '2026-10-16T12:01:00+08:00')
        first = self.ingest('《数学》第一次作业，请完成报告。', '2026-10-16T12:02:00+08:00')
        self.assertFalse(self.alerts.poll('2026-10-16T12:03:00+08:00')['enabled'])
        self.alerts.settings(True, '2026-10-16T12:04:00+08:00')
        self.assertEqual(self.alerts.poll('2026-10-16T12:05:00+08:00')['events'], [])
        second = self.ingest('《数学》第二次作业，请完成报告。', '2026-10-16T12:06:00+08:00')
        self.box.clear_messages([second['message']['id']])
        self.assertEqual(self.alerts.poll('2026-10-16T12:07:00+08:00')['events'], [])

    def test_first_course_inventory_does_not_emit_old_task_center_backlog(self):
        import hashlib
        from courseinbox.chaoxing import ingest_web_message
        key=hashlib.sha256(b'1|2|assignment').hexdigest()[:24]
        scanning=dict(enabled=True,inventory_epoch=0,sources={'task_center':{'discovery_complete':False,'discovered_sections':[]}})
        # Another course may remain unreadable: only this section establishes its baseline.
        completed=dict(enabled=True,inventory_epoch=0,sources={'task_center':{'discovery_complete':False,'discovered_sections':[key]}})
        self.alerts.poll('2026-10-16T12:00:00+08:00',sync_status=scanning)
        def capture(number,minute):
            return ingest_web_message(self.box,dict(kind='task_center',message_id='inventory-'+str(number),title='实验'+str(number),text='请提交报告',course='数学',conversation='一班',url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId='+str(number),platform_status='未提交',deadline='2030-10-30',captured_at=f'2026-10-16T12:{minute:02}:00+08:00',attachments=[]))
        capture(1,1)
        self.assertEqual(self.alerts.poll('2026-10-16T12:02:00+08:00',sync_status=scanning)['events'],[])
        capture(2,3)
        self.assertEqual(self.alerts.poll('2026-10-16T12:04:00+08:00',sync_status=completed)['events'],[])
        fresh=capture(3,5)
        events=self.alerts.poll('2026-10-16T12:06:00+08:00',sync_status=completed)['events']
        self.assertEqual(len(events),1)
        self.assertIn(fresh['message']['id'],events[0]['url'])
        self.alerts.ack([events[0]['id']])
        switched=dict(completed,inventory_epoch=1)
        capture(4,7)
        self.assertEqual(self.alerts.poll('2026-10-16T12:08:00+08:00',sync_status=switched)['events'],[])
        later=capture(5,9)
        self.assertIn(later['message']['id'],self.alerts.poll('2026-10-16T12:10:00+08:00',sync_status=switched)['events'][0]['url'])


if __name__ == '__main__':
    unittest.main()
