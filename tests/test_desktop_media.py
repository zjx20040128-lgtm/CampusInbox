import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseinbox.core import Inbox
from courseinbox.desktop_sync import DesktopSync


class DesktopMediaTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch('courseinbox.core.now_iso',return_value='2026-10-17T12:00:00+08:00');self.clock.start();self.addCleanup(self.clock.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.sync=DesktopSync(self.box,Path(__file__).resolve().parents[1],autostart=False);self.addCleanup(self.sync.close)
        self.sync.enabled=True

    def job(self):
        return dict(kind='course_notice',message_id='notice_media',title='《示例课程》第一次作业',text='',course='示例课程',conversation='示例课程',
            captured_at='2026-10-17T12:00:00+08:00',url='https://notice.chaoxing.com/pc/notice/media/detail',media_pending_count=0,
            attachments=[dict(name='通知图片1.png',kind='inline_image',url='https://p.ananas.chaoxing.com/star3/fixture.png',size=10,status='listed',content_base64=base64.b64encode(b'image').decode())])

    def receive(self,job,engine='windows-ocr/zh-Hans-CN',text='请提交实验报告。截止2026年10月30日。'):
        with patch('courseinbox.desktop_sync.extract_file',return_value=(text,engine)):
            self.sync.receive(dict(type='notice',job=copy.deepcopy(job)))

    def test_image_only_notice_creates_evidenced_draft_without_confirming_task(self):
        self.receive(self.job())
        messages=self.box.messages();self.assertEqual(len(messages),1)
        image=messages[0]['external']['attachments'][0]
        self.assertEqual(image['status'],'extracted');self.assertEqual(image['kind'],'inline_image')
        self.assertIn('实验报告',image['text']);self.assertNotIn('content_base64',json.dumps(messages))
        self.assertEqual(self.box.proposals()[0]['candidate']['deadline'],'2026-10-30')
        self.assertEqual(self.box.tasks(),[]);self.assertEqual(self.sync.status()['incomplete'],0)

    def test_partial_pdf_ocr_stays_partial_and_cannot_advance_complete_time(self):
        job=self.job();job['attachments'][0].update(name='作业说明.pdf',url='https://d0.cldisk.com/download/'+'a'*32);job['attachments'][0].pop('kind')
        self.receive(job,'windows-pdf-ocr/partial')
        self.assertEqual(self.box.messages()[0]['external']['attachments'][0]['status'],'partial')
        self.assertEqual(self.sync.status()['incomplete'],1)
        self.sync.receive(dict(type='source',source='notice',state='connected',checked=True,coverage='complete'))
        self.assertIsNone(self.sync.status()['sources']['notice']['last_complete_success'])

    def test_unreadable_media_remains_coverage_gap_even_when_image_ocr_succeeded(self):
        job=self.job();job['media_pending_count']=1
        self.receive(job)
        self.assertEqual(self.box.messages()[0]['external']['media_pending_count'],1)
        self.assertEqual(self.sync.status()['incomplete'],1)

    def test_later_discovered_image_enriches_existing_source_without_new_message(self):
        original=self.job();original['text']='请完成第一次作业，要求见通知图片。';original['attachments']=[]
        self.receive(original)
        upgraded=self.job();upgraded['text']=original['text'];self.receive(upgraded)
        self.assertEqual(len(self.box.messages()),1)
        self.assertEqual(len(self.box.messages()[0]['external']['attachments']),1)
        self.assertIn('实验报告',self.box.messages()[0]['text'])
        self.assertEqual(len(self.box.proposals()),1)

    def test_separate_ocr_deadline_and_submission_lines_are_preserved(self):
        self.receive(self.job(),text='请提交实验报告。\n截止：\n2026年10月30日。\n提交方式：学习通上传PDF。')
        candidate=self.box.proposals()[0]['candidate']
        self.assertEqual(candidate['deadline'],'2026-10-30')
        self.assertIn('学习通',candidate['submission_method'])

    def test_task_attachment_bytes_are_extracted_and_preserved_as_requirements(self):
        job=dict(kind='task_center',message_id='task_media_1',title='实验报告',text='要求见附件',description='要求见附件',
                 course='示例课程',conversation='一班',captured_at='2026-10-17T12:00:00+08:00',task_type='assignment',detail_state='read',
                 url='https://mooc1.chaoxing.com/mooc2/work/view?courseId=1&classId=2&workId=3',
                 attachments=[dict(name='作业要求.txt',url='https://d0.cldisk.com/download/'+'a'*32,status='listed',content_base64=base64.b64encode('提交报告PDF与源码ZIP。'.encode()).decode())])
        self.sync.receive(dict(type='task_center',job=job))
        message=self.box.messages()[0]
        self.assertEqual(message['external']['attachments'][0]['status'],'extracted')
        self.assertIn('源码ZIP',message['text'])
        self.assertTrue(any('源码ZIP' in value for value in self.box.proposals()[0]['candidate']['requirements']))
        self.assertNotIn('content_base64',json.dumps(message));self.assertEqual(self.box.tasks(),[])


if __name__=='__main__':unittest.main()
