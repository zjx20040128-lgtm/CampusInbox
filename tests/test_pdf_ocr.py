import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from courseinbox.core import ValidationError
from courseinbox.files import extract_file


class PdfOcrTests(unittest.TestCase):
    def pdf(self,pages=1):
        # A valid blank PDF, generated without the optional text-extraction library.
        objects=[b'<< /Type /Catalog /Pages 2 0 R >>',('<< /Type /Pages /Count '+str(pages)+' /Kids ['+' '.join(str(i+3)+' 0 R' for i in range(pages))+'] >>').encode()]
        objects += [b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>']*pages
        data=b'%PDF-1.4\n';offsets=[0]
        for index,obj in enumerate(objects,1):offsets.append(len(data));data+=str(index).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
        xref=len(data);data+=('xref\n0 '+str(len(offsets))+'\n0000000000 65535 f \n').encode()
        data+=b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
        return data+f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()

    def test_scanned_pdf_uses_local_windows_ocr(self):
        payload=dict(text='第一次作业，截止2026年10月30日。',language='zh-Hans-CN',complete=True)
        with patch.dict('sys.modules',{'pypdf':None}),patch('courseinbox.files._windows_extract',return_value=payload,create=True) as ocr:
            text,engine=extract_file('作业说明.pdf',self.pdf(),Path('.'))
        self.assertIn('第一次作业',text);self.assertEqual(engine,'windows-pdf-ocr');ocr.assert_called_once()

    def test_bounded_partial_pdf_keeps_text_and_reports_partial(self):
        payload=dict(text='已读取前10页的要求',language='zh-Hans-CN',complete=False)
        with patch('courseinbox.files._windows_extract',return_value=payload,create=True):
            text,engine=extract_file('说明.pdf',self.pdf(11),Path('.'))
        self.assertIn('前10页',text);self.assertTrue(engine.endswith('/partial'))

    def test_pdf_page_limit_is_checked_before_ocr(self):
        reader=SimpleNamespace(is_encrypted=False,pages=[None]*31)
        with patch.dict('sys.modules',{'pypdf':SimpleNamespace(PdfReader=lambda data:reader)}),patch('courseinbox.files._windows_extract',create=True) as ocr:
            with self.assertRaisesRegex(ValidationError,'30'):extract_file('说明.pdf',self.pdf(31),Path('.'))
        ocr.assert_not_called()

    def test_mixed_pdf_keeps_selectable_text_and_adds_missing_page_ocr(self):
        reader=SimpleNamespace(is_encrypted=False,pages=[SimpleNamespace(extract_text=lambda:'原有可选文字'),SimpleNamespace(extract_text=lambda:'')])
        payload=dict(pages=[dict(number=1,text='不覆盖原文'),dict(number=2,text='扫描页作业要求')],complete=True)
        with patch.dict('sys.modules',{'pypdf':SimpleNamespace(PdfReader=lambda data:reader)}),patch('courseinbox.files._windows_extract',return_value=payload):
            text,engine=extract_file('混合.pdf',self.pdf(2),Path('.'))
        self.assertEqual(text,'原有可选文字\n\n扫描页作业要求');self.assertEqual(engine,'windows-pdf-ocr')

    def test_empty_pdf_ocr_does_not_claim_success(self):
        with patch('courseinbox.files._windows_extract',return_value=dict(text='',complete=True),create=True):
            with self.assertRaises(ValidationError):extract_file('空白.pdf',self.pdf(),Path('.'))


if __name__=='__main__':unittest.main()
