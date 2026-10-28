"""Local extraction: Windows OCR, optional pypdf, and UTF-8 text."""
import json
import os
import re
import subprocess
import tempfile
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from .core import ValidationError

MAX_UPLOAD = 8 * 1024 * 1024


def _windows_extract(data,suffix,root):
    if os.name!='nt':raise ValidationError('本地图片与扫描 PDF 识别需要 Windows OCR，请复制文字导入。')
    script=Path(root)/'scripts'/'windows-ocr.ps1'
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    with tempfile.TemporaryDirectory(prefix='courseinbox-ocr-') as directory:
        target=Path(directory)/('source'+suffix);target.write_bytes(data)
        try:
            result=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-Path',str(target)],capture_output=True,timeout=90 if suffix=='.pdf' else 40,creationflags=0x08000000)
        except (OSError,subprocess.TimeoutExpired):raise ValidationError('Windows 本地识别启动失败或超时，请复制文字导入。') from None
        if result.returncode:raise ValidationError('本地识别失败，请检查文件、页数和 Windows OCR 语言。')
        try:return json.loads(result.stdout.decode('utf-8-sig').strip())
        except (UnicodeDecodeError,ValueError):raise ValidationError('本地识别返回格式无效，请复制文字导入。') from None

def normalize_ocr(text):
    # Windows Chinese OCR can add spaces between every ideograph and even date digits.
    text=re.sub(r'(?<=[\u4e00-\u9fff0-9《》【】：、，。])[^\S\r\n]+(?=[\u4e00-\u9fff0-9《》【】：、，。])','',text)
    return text.strip()

def extract_file(name, data, root):
    if len(data)>MAX_UPLOAD or not data:
        raise ValidationError('文件为空或超过 8 MB。')
    suffix=Path(name).suffix.lower()
    if suffix in ('.txt','.md'):
        try: return data.decode('utf-8-sig'), 'utf8-text'
        except UnicodeDecodeError: raise ValidationError('文本文件需为 UTF-8 编码。') from None
    if suffix=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info=archive.getinfo('word/document.xml')
                if info.file_size>20*1024*1024 or len(archive.infolist())>2000:
                    raise ValidationError('Word 文档展开后过大。')
                xml=archive.read(info)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise ValidationError('Word 文档包含不支持的 XML 声明。')
            document=ET.fromstring(xml)
            namespace='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            def paragraph_text(paragraph):
                return ''.join((node.text or '') if node.tag==namespace+'t' else ('\t' if node.tag==namespace+'tab' else '\n' if node.tag in (namespace+'br',namespace+'cr') else '') for node in paragraph.iter()).strip()
            paragraphs=[]
            container=document.find(namespace+'body')
            for element in container if container is not None else []:
                if element.tag==namespace+'tbl':
                    for row in element.findall(namespace+'tr'):
                        cells=[' / '.join(filter(None,(paragraph_text(p) for p in cell.iter(namespace+'p')))) for cell in row.findall(namespace+'tc')]
                        if any(cells): paragraphs.append(' | '.join(cells))
                else:
                    for paragraph in ([element] if element.tag==namespace+'p' else element.iter(namespace+'p')):
                        line=paragraph_text(paragraph)
                        if line: paragraphs.append(line)
            text='\n'.join(paragraphs)
        except ValidationError: raise
        except (KeyError,ValueError,ET.ParseError,zipfile.BadZipFile,RuntimeError,OSError):
            raise ValidationError('Word 文档无法读取，请检查文件。') from None
        if not text: raise ValidationError('Word 文档没有可提取文字。')
        return text,'docx-text'
    if suffix=='.pdf':
        pages=[]
        try:
            from pypdf import PdfReader
        except ImportError:PdfReader=None
        try:
            if PdfReader:
                reader=PdfReader(io.BytesIO(data))
                if reader.is_encrypted: raise ValidationError('暂不支持加密 PDF。')
                if len(reader.pages)>30: raise ValidationError('PDF 最多 30 页，请按通知拆分。')
                pages=[page.extract_text() or '' for page in reader.pages]
        except ValidationError: raise
        except Exception: raise ValidationError('PDF 无法读取，请检查文件。') from None
        if pages and all(page.strip() for page in pages):return '\n\n'.join(pages),'pdf-text'
        payload=_windows_extract(data,'.pdf',root)
        read={page['number']:normalize_ocr(page.get('text','')) for page in payload.get('pages',[])}
        text='\n\n'.join(page or read.get(index+1,'') for index,page in enumerate(pages)) if pages and read else normalize_ocr(payload.get('text',''))
        if not text.strip():raise ValidationError('PDF 中未识别到文字，请使用更清晰的文件或复制文本。')
        return text,'windows-pdf-ocr'+('' if payload.get('complete') is True else '/partial')
    if suffix not in ('.png','.jpg','.jpeg','.bmp','.webp'):
        raise ValidationError('支持 PNG/JPG/BMP/WebP 截图、UTF-8 文本、DOCX 和 PDF。')
    payload=_windows_extract(data,suffix,root)
    text=normalize_ocr(payload.get('text',''))
    if not text: raise ValidationError('截图中未识别到文字，请使用更清晰的截图。')
    return text,'windows-ocr/'+payload.get('language','')
