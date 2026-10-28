import tempfile
import unittest
from pathlib import Path

from courseinbox.core import Inbox, parse_message


AT = '2026-10-20T12:00:00+08:00'


class MultiTaskNoticeTests(unittest.TestCase):
    def test_semicolon_tasks_keep_their_own_deadlines_and_materials(self):
        items = parse_message('实验三：请提交报告，截止10月23日；实验四：请提交源代码，截止10月25日。', AT, '数据库', '一班')
        self.assertEqual([(x['title'], x['deadline']) for x in items], [('实验三', '2026-10-23'), ('实验四', '2026-10-25')])
        self.assertIn('报告', items[0]['requirements'])
        self.assertNotIn('源代码', items[0]['requirements'])
        self.assertIn('源代码', items[1]['requirements'])

    def test_new_task_sentence_keeps_continuation_with_previous_task(self):
        items = parse_message('实验三截止10月23日。请提交报告。实验四截止10月25日。请提交源代码。', AT, '数据库')
        self.assertEqual(len(items), 2)
        self.assertIn('报告', items[0]['requirements'])
        self.assertNotIn('源代码', items[0]['requirements'])
        self.assertIn('源代码', items[1]['requirements'])

    def test_each_explicit_course_is_respected(self):
        items = parse_message('《数据库》实验三截止10月23日；《操作系统》实验四截止10月25日。', AT)
        self.assertEqual([(x['course'], x['deadline']) for x in items], [('数据库', '2026-10-23'), ('操作系统', '2026-10-25')])

    def test_reference_to_other_task_is_not_a_new_independent_task(self):
        items = parse_message('实验三延期到下周一，其他要求不变，格式参考实验四。', AT, '数据库')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['deadline'], '2026-10-26')
        self.assertEqual(items[0]['operation'], 'update')

    def test_repeated_notice_title_and_body_remain_one_task(self):
        items = parse_message('第一次作业\n第一次作业，截止2026-09-15，请提交报告。', AT, '数据库')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['deadline'], '2026-09-15')

    def test_inline_book_title_cannot_replace_selected_course(self):
        items=parse_message('实验三：请阅读《参考资料》，截止10月23日；实验四：请提交源代码，截止10月25日。',AT,'数据库')
        self.assertEqual([x['course'] for x in items],['数据库','数据库'])

    def test_explicit_shared_deadline_or_postponement_applies_to_both_tasks(self):
        items=parse_message('实验三截止10月23日；实验四截止10月25日。以上均延期到下周一。',AT,'数据库')
        self.assertEqual([(x['deadline'],x['operation']) for x in items],[('2026-10-26','update'),('2026-10-26','update')])
        text='实验三：提交报告；实验四：提交源代码。以上两项均于10月25日截止。'
        items=parse_message(text,AT,'数据库')
        self.assertEqual([x['deadline'] for x in items],['2026-10-25','2026-10-25'])
        self.assertIn('报告',items[0]['requirements'])
        self.assertNotIn('源代码',items[0]['requirements'])
        for item in items:self.assertIn(item['evidence'],text)

    def test_two_tasks_and_later_update_preserve_confirmed_materials(self):
        with tempfile.TemporaryDirectory() as directory:
            box = Inbox(Path(directory) / 'inbox.sqlite3')
            result = box.ingest('实验三：请提交报告，截止10月23日；实验四：请提交源代码，截止10月25日。', captured_at=AT, course='数据库', scope='一班')
            self.assertEqual(len(result['proposals']), 2)
            self.assertEqual(box.tasks(), [])
            for proposal in result['proposals']:
                box.confirm(proposal['id'])
            updated = box.ingest('实验三延期到下周一，其他要求不变。', captured_at='2026-10-21T09:00:00+08:00', course='数据库', scope='一班')
            self.assertEqual(updated['proposals'][0]['action'], 'update')
            before = {t['title']: t for t in box.tasks()}
            self.assertEqual(before['实验三']['deadline'], '2026-10-23')
            box.confirm(updated['proposals'][0]['id'])
            after = {t['title']: t for t in box.tasks()}
            self.assertEqual(len(after), 2)
            self.assertEqual(after['实验三']['deadline'], '2026-10-26')
            self.assertEqual(after['实验四'], before['实验四'])
            self.assertEqual(after['实验三']['checklist'], before['实验三']['checklist'])


if __name__ == '__main__':
    unittest.main()
