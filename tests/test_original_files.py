import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import Mock
from courseinbox.core import Inbox, ValidationError
from courseinbox.chaoxing import ingest_web_message,scoped_token
from courseinbox.http import create_server
from courseinbox.original_files import OriginalFiles


class OriginalFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')
        self.message=ingest_web_message(self.box,dict(kind='task_center',message_id='files',title='图像增强',text='使用附件完成实验。',course='数字图像处理',conversation='一班',captured_at='2026-10-25T10:00:00+08:00',task_type='assignment',detail_state='read',url='https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=43',attachments=[dict(name='图像.bmp',url='https://d0.cldisk.com/download/'+'a'*32,status='listed')]))['message']
        self.store=OriginalFiles(self.box,Path(__file__).resolve().parents[1],lambda:None)
        self.store._fetch=Mock(return_value=b'BM-original-file')

    def test_download_caches_verified_bytes_without_modifying_tasks_or_messages(self):
        before=self.box.message(self.message['id']);tasks=self.box.tasks()
        self.assertEqual(self.store.read(self.message['id'],0),('图像.bmp',b'BM-original-file'))
        self.assertEqual(self.store.read(self.message['id'],0),('图像.bmp',b'BM-original-file'))
        self.assertEqual(self.store._fetch.call_count,1)
        self.assertEqual(self.box.message(self.message['id']),before);self.assertEqual(self.box.tasks(),tasks)
        cache=next((self.box.path.parent/'attachments').glob('*.bin'));cache.write_bytes(b'corrupted')
        self.store.read(self.message['id'],0);self.assertEqual(self.store._fetch.call_count,2)

    def test_index_and_empty_download_are_rejected_without_cache(self):
        with self.assertRaises(ValidationError):self.store.read(self.message['id'],9)
        self.store._fetch.assert_not_called()
        self.store._fetch.return_value=b''
        with self.assertRaises(ValidationError):self.store.read(self.message['id'],0)
        self.assertEqual(list((self.box.path.parent/'attachments').glob('*.bin')),[])

    def test_api_requires_main_token_and_returns_unicode_filename_and_bytes(self):
        token='test-original-file-main-token';server=create_server('127.0.0.1',0,self.box,token,reminder_port=0)
        server.original_files=self.store
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/api/messages/'+self.message['id']+'/attachments/0/download'
            for authorization in ('',scoped_token(token)):
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+authorization}))
                self.assertEqual(error.exception.code,401)
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token})) as response:
                self.assertEqual(response.read(),b'BM-original-file');self.assertIn('filename*=UTF-8',response.headers['Content-Disposition'])
                self.assertEqual(response.headers['Content-Type'],'application/octet-stream')
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
