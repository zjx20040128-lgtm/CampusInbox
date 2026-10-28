"""Authenticated original-file downloads with a local content-checked cache."""
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path
from .core import ValidationError
from .session_crypto import unseal

MAX_FILE=32*1024*1024


class OriginalFiles:
    def __init__(self,inbox,root,runtime):
        self.inbox=inbox;self.root=Path(root);self.runtime=runtime
        self.directory=inbox.path.parent/'attachments';self.lock=threading.Lock()

    def read(self,message_id,index):
        message=self.inbox.message(message_id);external=message.get('external',{})
        files=external.get('attachments',[])
        if external.get('platform')!='chaoxing-web' or external.get('kind')!='task_center':
            raise ValidationError('此附件请通过原消息打开。')
        if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(files):raise ValidationError('附件不存在，请刷新任务详情。')
        attachment=files[index]
        if not attachment.get('url'):raise ValidationError('附件下载地址尚未获取，请打开原任务核对。')
        name=re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',attachment['name']).strip('. ') or 'attachment.bin'
        key=hashlib.sha256(json.dumps([external['url'],attachment['url'],attachment['name']],ensure_ascii=False).encode()).hexdigest()
        target=self.directory/(key+'.bin');manifest=self.directory/(key+'.json')
        with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True)
            try:
                metadata=json.loads(manifest.read_text(encoding='utf-8'));data=target.read_bytes()
                if 0<len(data)<=MAX_FILE and hashlib.sha256(data).hexdigest()==metadata['sha256']:return name,data
            except (OSError,ValueError,KeyError,TypeError):pass
            data=self._fetch(message,attachment)
            if not isinstance(data,bytes) or not 0<len(data)<=MAX_FILE:raise ValidationError('附件为空或超过 32 MB，未保存文件。')
            temporary=target.with_suffix('.tmp');temporary.write_bytes(data);temporary.replace(target)
            metadata=dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
            temporary=manifest.with_suffix('.tmp');temporary.write_text(json.dumps(metadata),encoding='utf-8');temporary.replace(manifest)
            return name,data

    def _fetch(self,message,attachment):
        try:
            session=json.loads(unseal((self.inbox.path.parent/'chaoxing-sync/session.bin').read_bytes()))
            node,env=self.runtime();e=message['external']
            job=dict(kind='task_center',title=e['title'],url=e['url'],task_type=e.get('task_type','assignment'),course=message['course'],conversation=message['scope'],message_id=e['message_id'],text=e.get('task_body',''),field_evidence=e.get('field_evidence',{}),deadline=e.get('deadline'))
            if e.get('detail_url'):job['detail_url']=e['detail_url']
            result=subprocess.run([str(node),str(self.root/'desktop-sync/original-file.cjs')],input=json.dumps(dict(session=session,job=job,file=attachment)),text=True,encoding='utf-8',capture_output=True,timeout=100,env=env,creationflags=0x08000000 if os.name=='nt' else 0)
            payload=json.loads(result.stdout)
            if result.returncode or payload.get('error'):raise ValueError('download')
            encoded=payload['content_base64']
            if not isinstance(encoded,str) or len(encoded)>45*1024*1024:raise ValueError('size')
            return base64.b64decode(encoded,validate=True)
        except Exception:
            raise ValidationError('附件下载失败，请确认学习通登录有效且原任务允许下载，然后重试。') from None
