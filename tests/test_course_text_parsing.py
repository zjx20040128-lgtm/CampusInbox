import tempfile
import unittest
from pathlib import Path

from courseinbox.core import Inbox, parse_message


AT = '2026-10-23T19:07:00+08:00'


class CourseTextParsingTests(unittest.TestCase):
    def test_standalone_numbered_card_retains_descriptive_title(self):
        c=parse_message('作业2：图像增强',AT,scope='数字图像处理')[0]
        self.assertEqual(c['title'],'作业2：图像增强')
        self.assertEqual(c['course'],'')
        self.assertIsNone(c['deadline'])
    def test_course_prefix_and_explicit_labels(self):
        for heading in ('C语言程序设计：', 'C语言程序设计:', '课程：C语言程序设计\n',
                        '课程名称：C语言程序设计\n', '课程名：C语言程序设计\n', '测试课程：'):
            with self.subTest(heading=heading):
                candidate = parse_message(heading + '验收实验一，2026年10月30日20:00前提交PDF报告。', AT)[0]
                self.assertEqual(candidate['course'], '测试课程' if heading == '测试课程：' else 'C语言程序设计')
                self.assertEqual(candidate['title'], '实验一')
                self.assertEqual(candidate['deadline'], '2026-10-30T20:00:00+08:00')

    def test_course_prefix_takes_priority_over_reference_book(self):
        candidate = parse_message('C语言程序设计：实验一，参考《C语言入门》，10月30日前提交报告。', AT)[0]
        self.assertEqual(candidate['course'], 'C语言程序设计')

    def test_selected_course_remains_authoritative(self):
        candidate = parse_message('C语言程序设计：实验一，10月30日前提交报告。', AT, '用户选择的课程')[0]
        self.assertEqual(candidate['course'], '用户选择的课程')

    def test_instruction_and_task_labels_are_not_courses(self):
        for heading in ('任务名称', '作业名称', '任务', '标题', '作业', '实验一', '截止时间',
                        '提交方式', '通知', '重要通知', '提醒', '请注意'):
            with self.subTest(heading=heading):
                candidate = parse_message(heading + '：实验一，10月30日前提交报告。', AT)[0]
                self.assertEqual(candidate['course'], '')

    def test_create_then_extension_matches_same_task(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory) / 'test.sqlite3')
            created = inbox.ingest('C语言程序设计：实验一，2026年10月30日20:00前提交PDF报告。', captured_at=AT)
            task = inbox.confirm(created['proposals'][0]['id'])
            extension = inbox.ingest('C语言程序设计：实验一延期至2026年11月2日20:00，其他要求不变。', captured_at='2026-10-23T19:08:00+08:00')
            proposal = extension['proposals'][0]
            self.assertEqual(proposal['action'], 'update')
            self.assertEqual(proposal['target_id'], task['id'])
            updated = inbox.confirm(proposal['id'])
            self.assertEqual(updated['deadline'], '2026-11-02T20:00:00+08:00')
            self.assertEqual(len(inbox.tasks()), 1)
            self.assertEqual(updated['checklist'], task['checklist'])
