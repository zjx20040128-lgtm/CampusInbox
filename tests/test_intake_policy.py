import unittest
from copy import deepcopy
from courseinbox.intake_policy import archive_reason, automatic_candidate, should_archive_automatic


NOW = '2026-10-16T17:05:00+08:00'


class AutomaticIntakePolicyTests(unittest.TestCase):
    def message(self, text='第一次作业，截止2026-09-15。', **changes):
        value = dict(text=text, captured_at='2026-09-15T12:00:00+08:00', received_at=NOW,
                     external=dict(platform='chaoxing-web', kind='course_notice'))
        value.update(changes)
        return value

    def candidate(self, **changes):
        value = dict(title='第一次作业', operation='create', deadline='2026-09-15', date_precision='date',
                     deadline_evidence='2026-09-15', warnings=[], deadline_change_requested=False)
        value.update(changes)
        return value

    def test_expired_explicit_deadline_is_archived(self):
        self.assertTrue(should_archive_automatic(self.candidate(), self.message(), NOW))
        self.assertEqual(archive_reason(self.candidate(), self.message(), NOW), 'deadline_passed')

    def test_old_posted_time_does_not_close_current_or_undated_work(self):
        for deadline, text in ((None, '请提交第一次作业。'), ('2026-10-30', '第一次作业，截止2026-10-30。')):
            with self.subTest(deadline=deadline):
                self.assertFalse(should_archive_automatic(self.candidate(deadline=deadline), self.message(text), NOW))

    def test_only_automatic_chaoxing_messages_are_eligible(self):
        for external in (None, {}, dict(platform='other'), dict(platform='chaoxing-web', kind='manual')):
            with self.subTest(external=external):
                self.assertFalse(should_archive_automatic(self.candidate(), self.message(external=external), NOW))

    def test_untrusted_date_without_deadline_semantics_cannot_archive(self):
        source = self.message('作业名称：作业20260915\n发布时间：2026-09-15\n请提交实验报告。')
        candidate = self.candidate()
        before = deepcopy(candidate)
        refined = automatic_candidate(candidate, source)
        self.assertIsNone(refined['deadline'])
        self.assertEqual(refined['date_precision'], 'unknown')
        self.assertEqual(candidate, before, 'refining must leave original candidate evidence intact')
        self.assertFalse(should_archive_automatic(candidate, source, NOW))

    def test_date_only_deadline_ends_at_the_following_beijing_midnight(self):
        candidate = self.candidate(deadline='2026-10-16')
        message = self.message('第一次作业，截止2026-10-16。')
        self.assertFalse(should_archive_automatic(candidate, message, '2026-10-16T23:59:59+08:00'))
        self.assertTrue(should_archive_automatic(candidate, message, '2026-10-17T00:00:00+08:00'))

    def test_exact_deadline_is_not_past_until_after_the_specified_instant(self):
        candidate = self.candidate(deadline='2026-10-16T17:05:00+08:00')
        message = self.message('第一次作业，截止2026-10-16 17:05。')
        self.assertFalse(should_archive_automatic(candidate, message, NOW))
        self.assertTrue(should_archive_automatic(candidate, message, '2026-10-16T17:05:01+08:00'))

    def test_datetime_offsets_are_compared_as_instants(self):
        candidate = self.candidate(deadline='2026-10-16T09:04:00+00:00')
        message = self.message('第一次作业，截止2026-10-16 17:04。')
        self.assertTrue(should_archive_automatic(candidate, message, NOW))

    def test_update_cancel_and_deadline_change_are_not_new_historical_work(self):
        for changes in (dict(operation='update'), dict(operation='cancel'), dict(deadline_change_requested=True)):
            with self.subTest(changes=changes):
                self.assertFalse(should_archive_automatic(self.candidate(**changes), self.message('第一次作业已结束，截止2026-09-15。'), NOW))

    def test_explicit_ended_and_submitted_text_is_archived(self):
        for text, reason in (('任务结束提醒；实验报告', 'task_ended'), ('第一次作业已结束；请查看结果。', 'task_ended'),
                             ('实验报告状态：已提交', 'already_submitted'), ('你已提交第一次作业。', 'already_submitted')):
            with self.subTest(text=text):
                self.assertEqual(archive_reason(self.candidate(deadline=None), self.message(text), NOW), reason)

    def test_negative_status_or_other_peoples_submission_does_not_close_work(self):
        for text in ('第一次作业尚未结束，请提交。', '第一次作业未提交，请尽快完成。', '已有同学提交了第一次作业，请其余同学完成。',
                     '请在作业结束前提交实验报告。', '本次作业不再延期，请完成。', '老师已提交课程成绩，请提交第一次作业。'):
            with self.subTest(text=text):
                self.assertFalse(should_archive_automatic(self.candidate(deadline=None), self.message(text), NOW))

    def test_structured_status_and_deadline_are_authoritative_even_when_detail_unavailable(self):
        for status, reason in (('已提交 待批阅', 'already_submitted'), ('待批阅', 'already_submitted'), ('待批改', 'already_submitted'), ('已结束', 'task_ended'), ('已截止', 'task_ended')):
            with self.subTest(status=status):
                message = self.message('请完成实验。', external=dict(platform='chaoxing-web', kind='task_center', platform_status=status, detail_state='unavailable'))
                self.assertEqual(archive_reason(self.candidate(deadline=None), message, NOW), reason)
        message = self.message('任务名称：作业20260915', external=dict(platform='chaoxing-web', kind='task_center', platform_status='未提交', deadline='2026-09-15'))
        self.assertTrue(should_archive_automatic(self.candidate(), message, NOW))

    def test_deadline_recognition_uses_candidate_block_not_another_tasks_status(self):
        message = self.message('第一次作业已结束。\n\n第二次作业请完成。')
        candidate = self.candidate(title='第二次作业', deadline=None, evidence='第二次作业请完成。')
        self.assertFalse(should_archive_automatic(candidate, message, NOW))

    def test_submit_by_date_and_end_time_field_are_explicit_deadlines(self):
        for text, expected in (('第一次作业请于2026-09-15前提交。', '2026-09-15'),
                               ('任务名称：实验报告\n结束时间：2026-10-30 23:59', '2026-10-30T23:59:00+08:00')):
            with self.subTest(text=text):
                refined = automatic_candidate(self.candidate(deadline=None), self.message(text))
                self.assertEqual(refined['deadline'], expected)

    def test_effective_extension_uses_new_deadline(self):
        message = self.message('第一次作业原截止2026-09-15，现延期到2026-10-30，请提交报告。')
        candidate = self.candidate(operation='update', deadline_change_requested=True)
        self.assertEqual(automatic_candidate(candidate, message)['deadline'], '2026-10-30')

    def test_unmatched_cancellation_language_cannot_be_hidden_by_old_deadline(self):
        from courseinbox.core import parse_message
        message = self.message('任务已取消，截止2026-09-15。')
        candidate = parse_message(message['text'], message['captured_at'])[0]
        self.assertFalse(should_archive_automatic(candidate, message, NOW))

    def test_partial_completion_and_group_conditions_do_not_close_the_task(self):
        from courseinbox.core import parse_message
        for text in ('《数学》第一次作业已完成一半，请于2026年10月30日提交实验报告。',
                     '《数学》第一次作业已完成的同学请忽略，未完成的同学请于2026年10月30日提交报告。',
                     '《数学》第一次作业已提交的同学请忽略，其余同学请于2026年10月30日提交报告。',
                     '《数学》第一次作业已完成第一部分，请于2026年10月30日提交其余报告。',
                     '《数学》第一次作业已提交第一部分，请于2026年10月30日提交其余报告。',
                     '你已提交第一次作业的第一部分实验报告，请于2026年10月30日提交其余内容。',
                     '如果第一次作业已完成，请检查报告并于2026年10月30日提交。'):
            with self.subTest(text=text):
                message = self.message(text)
                candidate = parse_message(text, message['captured_at'])[0]
                self.assertEqual(archive_reason(candidate, message, NOW), '')

    def test_complete_status_statements_still_close_the_task(self):
        from courseinbox.core import parse_message
        for text, reason in (('《数学》第一次作业已完成。', 'task_ended'),
                             ('《数学》第一次作业已结束，请查看结果。', 'task_ended'),
                             ('《数学》第一次作业已提交。', 'already_submitted'),
                             ('你已提交第一次作业。', 'already_submitted')):
            with self.subTest(text=text):
                message = self.message(text)
                candidate = parse_message(text, message['captured_at'])[0]
                self.assertEqual(archive_reason(candidate, message, NOW), reason)

    def test_unfinished_second_task_does_not_reopen_the_first_ended_task(self):
        from courseinbox.core import parse_message
        message = self.message('《数学》第一次作业已结束。\n\n《数学》第二次作业尚未完成，请于2026年10月30日提交报告。')
        candidates = parse_message(message['text'], message['captured_at'])
        self.assertEqual(len(candidates), 2)
        self.assertEqual(archive_reason(candidates[0], message, NOW), 'task_ended')
        self.assertEqual(archive_reason(candidates[1], message, NOW), '')
