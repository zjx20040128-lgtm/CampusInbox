import copy
import tempfile
import unittest
from pathlib import Path
from courseinbox.core import Inbox
from courseinbox.chaoxing import ingest_web_message, merge_task_attachments


class AttachmentDiscoveryTests(unittest.TestCase):
    def payload(self):
        return dict(kind='task_center',message_id='discovered_files',title='图像增强',text='使用image1.bmp完成图像增强实验。',
                    course='数字图像处理',conversation='一班',captured_at='2026-10-25T10:00:00+08:00',task_type='assignment',
                    detail_state='read',media_pending_count=1,attachments=[],
                    url='https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId=43')

    def file(self,name='image1.bmp',char='a'):
        return dict(name=name,url='https://d0.cldisk.com/download/'+char*32,status='skipped',error='原文件已关联，未自动提取文字。')

    def test_discovered_files_enrich_same_source_without_changing_confirmed_task(self):
        with tempfile.TemporaryDirectory() as directory:
            box=Inbox(Path(directory)/'inbox.sqlite3');payload=self.payload()
            original=ingest_web_message(box,payload);task=box.confirm(original['proposals'][0]['id'])
            before=box.tasks()[0]
            payload.update(attachments=[self.file()],media_pending_count=0)
            enriched=ingest_web_message(box,payload)
            self.assertTrue(enriched.get('enriched'))
            self.assertEqual(len(box.messages()),1)
            self.assertEqual(enriched['message']['id'],original['message']['id'])
            self.assertEqual(box.task_detail(task['id'])['sources'][0]['external']['attachments'][0]['name'],'image1.bmp')
            self.assertEqual(box.tasks()[0],before)

    def test_new_discovery_preserves_existing_extracted_text(self):
        from courseinbox.chaoxing import normalize_web_message
        payload=self.payload();payload['attachments']=[dict(self.file('要求.txt'),status='extracted',text='提交实验报告。')]
        old=normalize_web_message(payload)['external'];new=copy.deepcopy(old)
        new['attachments'][0].update(status='listed',text='');new['attachments'].append(self.file('data.zip','b'))
        merged,conflict=merge_task_attachments(old,new,'数字图像处理','一班')
        self.assertIsNotNone(merged);self.assertFalse(conflict)
        self.assertEqual(merged['attachments'][0]['text'],'提交实验报告。');self.assertEqual(len(merged['attachments']),2)
        new['task_body']='另一个版本的要求'
        self.assertIsNone(merge_task_attachments(old,new,'数字图像处理','一班')[0])

    def test_existing_file_cannot_be_silently_replaced_or_removed(self):
        from courseinbox.chaoxing import normalize_web_message
        payload=self.payload();payload['attachments']=[self.file()]
        old=normalize_web_message(payload)['external'];new=copy.deepcopy(old)
        new['attachments']=[self.file(char='b')]
        self.assertIsNone(merge_task_attachments(old,new,'数字图像处理','一班')[0])
        new['attachments']=[]
        self.assertIsNone(merge_task_attachments(old,new,'数字图像处理','一班')[0])


if __name__=='__main__':unittest.main()
