import unittest
import io
import zipfile
from pathlib import Path
from courseinbox.files import extract_file
from courseinbox.core import ValidationError
from courseinbox.files import normalize_ocr
from courseinbox.core import parse_message

class OcrTests(unittest.TestCase):
    def test_chinese_ocr_word_spaces_do_not_break_task_or_date(self):
        raw='《 软 件 工 程 》 第 三 次 作 业\n请 提 交 实 验 报 告 、 源 代 码 。\n截 止 ： 2026 年 1 0 月 1 2 日 23 ： 59 。'
        text=normalize_ocr(raw)
        p=parse_message(text,'2026-10-03T16:00:00+08:00')[0]
        self.assertEqual(p['title'],'第三次作业')
        self.assertEqual(p['course'],'软件工程')
        self.assertEqual(p['deadline'],'2026-10-12T23:59:00+08:00')
        self.assertIn('源代码',p['requirements'])
    def test_latin_word_separators_preserved(self):
        self.assertIn('SQL scripts',normalize_ocr('请 提 交 SQL scripts 文 件'))

if __name__=='__main__': unittest.main()

class DocumentTests(unittest.TestCase):
    def docx(self,xml):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('word/document.xml',xml)
        return data.getvalue()
    def test_docx_keeps_paragraphs_and_table_requirements(self):
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>请阅读两份材料</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>准备三个讨论问题</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
        text,engine=extract_file('课前阅读说明.docx',self.docx(xml),Path('.'))
        self.assertEqual(engine,'docx-text')
        self.assertEqual(text,'请阅读两份材料\n准备三个讨论问题')
    def test_docx_rejects_invalid_entity_and_oversized_expansion(self):
        for data in [b'not a zip',self.docx('<!DOCTYPE document [<!ENTITY x "value">]><document>&x;</document>'),self.docx('x'* (20*1024*1024+1))]:
            with self.assertRaises(ValidationError):extract_file('bad.docx',data,Path('.'))
