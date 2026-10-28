"""Local evaluation workspace; message/task tables are never edited here."""
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from .core import Conflict, Inbox, NotFound, ValidationError, now_iso, parse_timestamp
from .message_timing import annotate
from .benchmark import prepare_holdout, compare_reports
from .evaluation import (EvaluationCancelled, _key, evaluate, local_provider,
                         model_runner, ollama_data, prepare_labels, validate_labels, ERROR_TYPES)


class EvaluationWorkspace:
    def __init__(self, inbox, root, agent):
        self.inbox, self.root = inbox, Path(root)
        self.directory = Path(inbox.path).parent
        self.lock = threading.RLock()
        self.jobs, self.active, self.thread, self.closed = {}, None, None, False
        provider = agent.provider
        self.base = provider.base_url if provider and getattr(provider,'kind','')=='ollama' else 'http://127.0.0.1:11434'
        self.preferred = getattr(provider,'model','') if provider else ''

    @staticmethod
    def _read(path,with_revision=False):
        if path.stat().st_size > 12*1024*1024:raise ValidationError('评测文件过大。')
        content=path.read_bytes()
        value=json.loads(content.decode('utf-8-sig'))
        return (value,hashlib.sha256(content).hexdigest()) if with_revision else value

    @staticmethod
    def _files(directory):
        if not directory.is_dir():return []
        return [p for p in directory.glob('*.json') if p.resolve().is_relative_to(directory.resolve())]

    def _dataset(self, name):
        if not isinstance(name,str) or not name or len(name)>160 or Path(name).name!=name or '/' in name or '\\' in name:
            raise ValidationError('请选择已有评测数据集。')
        path = self.directory/'verification'/name
        if path not in self._files(path.parent):raise ValidationError('请选择已有评测数据集。')
        value,revision = self._read(path,with_revision=True)
        rows, unreviewed = validate_labels(value)
        return path,value,rows,unreviewed,revision

    def datasets(self):
        result=[]
        for path in sorted(self._files(self.directory/'verification'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                _,value,rows,pending,revision=self._dataset(path.name)
                result.append(dict(id=path.name,name='已有人工标注' if value['schema']==1 else '通知标注 · '+value.get('prepared_at',path.stem)[:19].replace('T',' '),
                                   schema=value['schema'],total=len(rows)+pending,reviewed=len(rows),unreviewed=pending,revision=revision,
                                   partitioned=value.get('origin')=='prospective_local_holdout',
                                   split_reviewed={s:sum(r.get('split')==s and r.get('reviewed') is True for r in value['labels']) for s in ('development','holdout')}))
            except (OSError,ValueError,TypeError,KeyError):continue
        return dict(datasets=result)

    def prepare(self,body):
        if set(body)-{'limit','holdout'} or type(body.get('holdout',False)) is not bool:raise ValidationError('准备标注的参数无效。')
        limit=body.get('limit',200)
        if type(limit) is not int or not 1<=limit<=200:raise ValidationError('请选择1至200条消息。')
        directory=self.directory/'verification';directory.mkdir(exist_ok=True)
        path=directory/('notice-labels-workbench-'+uuid.uuid4().hex[:12]+'.json')
        if body.get('holdout'):
            exclusions=[]
            for existing in self._files(directory):
                try:self._dataset(existing.name)
                except (OSError,ValueError,TypeError,KeyError):continue
                exclusions.append(existing)
            with tempfile.TemporaryDirectory(prefix='courseinbox-holdout-') as tmp:
                result=prepare_holdout(self.inbox.path,Path(tmp)/'new',exclusions)
                path=directory/('holdout-'+uuid.uuid4().hex[:12]+'.json')
                with path.open('x',encoding='utf-8') as target:
                    target.write(Path(result.pop('labels')).read_text(encoding='utf-8'))
        else:result=prepare_labels(self.inbox.path,path,limit)
        return dict(result,id=path.name)

    def labels(self,query):
        path,value,_,_,revision=self._dataset(query.get('dataset',[''])[0])
        try:limit=int(query.get('limit',['20'])[0]);offset=int(query.get('offset',['0'])[0])
        except (ValueError,TypeError):raise ValidationError('标注分页参数无效。') from None
        if not 1<=limit<=50 or offset<0:raise ValidationError('标注分页参数无效。')
        if query.get('export')==['1']:
            return dict(schema=value['schema'],labels=[{k:v for k,v in row.items() if k in ('key','reviewed','expected_tasks','task','deadline','operation','split','group')} for row in value['labels'] if value['schema']==1 or row.get('reviewed') is True]),'courseinbox-labels.json'
        index={}
        with self.inbox.connection() as db:
            db.execute('BEGIN')
            messages=[json.loads(row['data']) for row in db.execute('SELECT data FROM messages ORDER BY rowid')]
            for message in annotate(self.inbox,db,messages):
                index[_key(message)]=message
                external=message.get('external',{})
                if external.get('kind')=='course_notice' and isinstance(external.get('message_id'),str):
                    index[hashlib.sha256(external['message_id'].encode()).hexdigest()[:16]]=message
        items=[]
        for row in value['labels'][offset:offset+limit]:
            legacy=index.get(row['key'],{})
            text=row.get('review_text',legacy.get('text','原文未保存在此工作文件，请在消息收件箱核对。'))
            timing=legacy.get('timing',{});deadline=timing.get('deadline');display=text
            if legacy.get('external',{}).get('kind',row.get('source_kind'))=='task_center':
                label=('截止：'+(parse_timestamp(deadline).strftime('%Y-%m-%d %H:%M') if len(deadline)>10 else deadline)) if deadline else '截止未获取'
                display=re.sub(r'(?:剩余|还有)\s*(?:\d+(?:\.\d+)?\s*(?:个)?(?:天|小时|分钟|分|秒)\s*)+',lambda _:label,text)
            items.append(dict(key=row['key'],reviewed=value['schema']==1 or row.get('reviewed') is True,
                              split=row.get('split'),
                              expected_tasks=deepcopy(row.get('expected_tasks',[])),legacy_task=row.get('task') if value['schema']==1 else None,
                              text=text,display_text=display,deadline=deadline,deadline_source=timing.get('deadline_source','unknown'),
                              course=row.get('review_course',legacy.get('course','')),scope=row.get('review_scope',legacy.get('scope','')),
                              published_at=timing.get('published_at') if legacy else row.get('review_published_at')))
        return dict(dataset=path.name,schema=value['schema'],revision=revision,total=len(value['labels']),items=items,offset=offset,limit=limit),None

    def save_label(self,body):
        if set(body)!={'dataset','key','revision','reviewed','expected_tasks'} or type(body['reviewed']) is not bool:
            raise ValidationError('标注参数无效。')
        with self.lock:
            path,value,_,_,revision=self._dataset(body['dataset'])
            if value['schema']!=2:raise ValidationError('旧版标签仅支持查看，请选择逐任务标注数据集。')
            if body['revision']!=revision:raise Conflict('标注已在其他窗口更改，请重新加载后核对。')
            row=next((row for row in value['labels'] if row['key']==body['key']),None)
            if row is None:raise ValidationError('请选择此数据集中的消息。')
            tasks=body['expected_tasks']
            # Validate even a saved-but-not-reviewed draft; its answer is never guessed.
            validate_labels(dict(schema=2,labels=[dict(key=row['key'],reviewed=True,expected_tasks=tasks)]))
            if any(len(t['title'])>160 or len(t.get('course',''))>100 or len(t.get('scope',''))>100 for t in tasks):raise ValidationError('任务名称、课程或班级过长。')
            row.update(reviewed=body['reviewed'],expected_tasks=tasks)
            validate_labels(value)
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            os.replace(temporary,path)
            return dict(ok=True,revision=hashlib.sha256(path.read_bytes()).hexdigest())

    def models(self):
        try:
            values=ollama_data(self.base,'/api/tags').get('models',[])
            names=[m['name'] for m in values if isinstance(m,dict) and isinstance(m.get('name'),str) and len(m['name'])<=200][:50]
            return dict(available=True,models=names,preferred=self.preferred)
        except (OSError,ValueError,TypeError,KeyError):
            return dict(available=False,models=[],preferred='',message='未连接本机 Ollama。打开 Ollama 后点击刷新模型。')

    @staticmethod
    def _public_report(value):
        runs=value.get('runs') if isinstance(value,dict) else None
        if runs is None and isinstance(value,dict) and value.get('mode') in ('rules','qwen'):runs=[value]
        if not isinstance(runs,list) or not runs:return None
        numbers=('labeled','unreviewed','matched','missing','errors','limited','model_fallbacks','sample_cases','legacy_detection_only_cases','unsupported_deadlines','task_precision','task_recall','deadline_exact','deadline_cases','update_recall','update_cases','operation_exact')
        def numeric(value):return type(value) in (int,float) and math.isfinite(value) and value>=0
        def fields(value,keys):return {k:value[k] for k in keys if isinstance(value,dict) and k in value and (numeric(value[k]) or value[k] is None)}
        clean=[]
        for run in runs[:5]:
            if not isinstance(run,dict) or run.get('mode') not in ('rules','qwen'):continue
            item=dict(mode=run['mode'],**fields(run,numbers))
            model=run.get('model','')
            item['model']=model if isinstance(model,str) and re.fullmatch(r'[a-zA-Z0-9_./:@-]{0,200}',model) else ''
            if run.get('status') in ('not_installed','completed','failed'):item['status']=run['status']
            item['counts']=fields(run.get('counts'),('tp','fp','fn'))
            item['routing']=fields(run.get('routing'),('rules','rules_verified','model_assisted','relative_extension'))
            item['error_type_counts']=fields(run.get('error_type_counts'),ERROR_TYPES)
            item['latency_ms']=fields(run.get('latency_ms'),('samples','mean','p50','p95','maximum'))
            item['target_evidence_complete']=run.get('target_evidence_complete') is True
            item['cases']=[]
            for case in run.get('cases',[]) if isinstance(run.get('cases'),list) else []:
                if not isinstance(case,dict) or not re.fullmatch(r'[a-f0-9]{16,64}',str(case.get('key',''))):continue
                row=dict(key=case['key'],**fields(case,('expected','predicted','matched','elapsed_ms','deadline_cases','deadline_right','operation_cases','operation_right','unsupported_deadlines')))
                row['status']=case.get('status') if case.get('status') in ('missing','ambiguous','error','evaluated') else 'error'
                row.update(fallback=case.get('fallback') is True,limited=case.get('limited') is True)
                row['error_types']=[e for e in case.get('error_types',[]) if e in ERROR_TYPES] if isinstance(case.get('error_types'),list) else []
                row['route']=case.get('route') if case.get('route') in ('rules','rules_verified','model_assisted','relative_extension') else None
                item['cases'].append(row)
            snapshot=run.get('loaded_model_snapshot',[])
            if isinstance(snapshot,list):item['loaded_model_snapshot']=[fields(row,('size','size_vram')) for row in snapshot if isinstance(row,dict)][:10]
            clean.append(item)
        if not clean:return None
        comparisons=[]
        for run in clean[1:]:
            try:comparisons.append(dict(model=run['model'],**compare_reports(clean[0],run)))
            except (ValidationError,KeyError,TypeError):continue
        return dict(schema_version=1,generated_at=value.get('generated_at',runs[0].get('generated_at')),
                    dataset=value.get('dataset'),dataset_revision=value.get('dataset_revision'),runs=clean,comparisons=comparisons)

    def _reports(self):
        directories=[('saved',self.directory/'evaluation')]
        if self.directory.resolve()==(self.root/'data').resolve():directories.append(('legacy',self.root/'artifacts/evaluation'))
        result={}
        for prefix,directory in directories:
            for path in sorted(self._files(directory),key=lambda p:p.stat().st_mtime,reverse=True)[:80]:
                try:
                    report=self._public_report(self._read(path))
                    if report:result[prefix+'--'+path.name]=(path,report)
                except (OSError,ValueError,TypeError,KeyError):continue
        return result

    def reports(self):
        reports=self._reports()
        rows=[dict(id=key,generated_at=value[1]['generated_at'],dataset=value[1]['dataset'],runs=len(value[1]['runs']),labeled=value[1]['runs'][0].get('labeled',0)) for key,value in reports.items()]
        rows.sort(key=lambda r:str(r['generated_at'] or ''),reverse=True)
        return dict(reports=rows[:40])

    def report(self,ident):
        if not isinstance(ident,str) or len(ident)>220 or '/' in ident or '\\' in ident:raise ValidationError('报告编号无效。')
        value=self._reports().get(ident)
        if not value:raise ValidationError('报告不存在。')
        return value[1]

    def job(self,ident=None):
        with self.lock:
            ident=ident or self.active
            if not ident:return dict(state='idle')
            if ident not in self.jobs:raise NotFound('评测记录不存在。')
            return deepcopy({k:v for k,v in self.jobs[ident].items() if k!='cancel'})

    def start(self,body):
        if set(body)-{'dataset','mode','models','split'} or body.get('mode') not in ('rules','compare'):
            raise ValidationError('请选择规则评测或本地模型对比。')
        with self.lock:
            if self.closed:raise ValidationError('评测服务正在停止。')
            if self.active and self.jobs[self.active]['state'] in ('queued','running','cancelling'):raise Conflict('已有评测正在运行，请等待完成或停止。')
            _,value,rows,_,revision=self._dataset(body.get('dataset'))
            split=body.get('split') or ('holdout' if value.get('origin')=='prospective_local_holdout' else None)
            if split not in (None,'development','holdout'):raise ValidationError('评测分组无效。')
            if split:
                if any(r.get('split') not in ('development','holdout') for r in value['labels']):raise ValidationError('标注文件未划分开发集与留出集。')
                value=dict(value,labels=[r for r in value['labels'] if r['split']==split])
                rows,_=validate_labels(value)
            if not rows:raise ValidationError('请先人工核对并保存至少一条标注。')
            models=body.get('models',[])
            if not isinstance(models,list) or len(models)>3 or any(not isinstance(m,str) for m in models):raise ValidationError('最多选择三个本机模型。')
            models=list(dict.fromkeys(models)) if body['mode']=='compare' else []
            if body['mode']=='compare':
                available=self.models()
                if not models or not available['available'] or any(m not in available['models'] for m in models):raise ValidationError('请选择已经安装并可连接的本机模型。')
            ident=uuid.uuid4().hex
            self.jobs={key:job for key,job in self.jobs.items() if job['state'] in ('running','queued','cancelling')}
            self.jobs[ident]=dict(id=ident,state='queued',dataset=body['dataset'],split=split,completed=0,total=len(rows)*(1+len(models)),current_model='rules',results=[],started_at=now_iso(),cancel=threading.Event())
            self.active=ident
            self.thread=threading.Thread(target=self._run,args=(ident,deepcopy(value),revision,models),daemon=True)
            self.thread.start()
            return self.job(ident)

    def _run(self,ident,labels,revision,models):
        job=self.jobs[ident];stop=job['cancel']
        try:
            with tempfile.TemporaryDirectory(prefix='courseinbox-web-evaluation-') as directory:
                directory=Path(directory);database=directory/'snapshot.sqlite3';label_path=directory/'labels.json'
                label_path.write_text(json.dumps(labels,ensure_ascii=False),encoding='utf-8')
                with closing(sqlite3.connect(Path(self.inbox.path).resolve().as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(database)) as target:source.backup(target)
                offset=0
                for model in ['']+models:
                    if stop.is_set():raise EvaluationCancelled()
                    with self.lock:job.update(state='running',current_model=model or 'rules')
                    def progress(done,total):
                        with self.lock:job.update(completed=offset+done)
                    runner=None
                    if model:
                        provider=local_provider(self.base,model)
                        class CancellableProvider:
                            kind='ollama'
                            def chat(self,messages,tools):
                                if stop.is_set():raise EvaluationCancelled()
                                result=provider.chat(messages,tools)
                                if stop.is_set():raise EvaluationCancelled()
                                return result
                        wrapped=CancellableProvider();wrapped.model=model
                        runner=model_runner(Inbox(directory/('context-'+str(offset)+'.sqlite3')),wrapped)
                    result=evaluate(database,label_path,mode='qwen' if model else 'rules',model=model,runner=runner,progress=progress,cancel=stop.is_set,split=job.get('split'))
                    if model:
                        try:
                            result['loaded_model_snapshot']=[{k:p[k] for k in ('size','size_vram') if type(p.get(k)) is int} for p in ollama_data(self.base,'/api/ps').get('models',[]) if p.get('name')==model]
                        except (OSError,ValueError,TypeError):pass
                    with self.lock:job['results'].append(result)
                    offset+=result['labeled']
                # Cancellation and final report publication share one commit lock.
                with self.lock:
                    if stop.is_set():raise EvaluationCancelled()
                    report=dict(schema_version=1,generated_at=now_iso(),dataset=job['dataset'],dataset_revision=revision,runs=job['results'])
                    target=self.directory/'evaluation';target.mkdir(exist_ok=True)
                    name='report-'+ident+'.json'
                    (target/name).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                    job.update(state='completed',completed=job['total'],report_id='saved--'+name)
        except EvaluationCancelled:
            with self.lock:job.update(state='cancelled')
        except Exception:
            with self.lock:job.update(state='failed',error='评测未完成，请核对数据集和本机模型连接后重试。')

    def cancel(self,body):
        if set(body)!={'id'}:raise ValidationError('请选择要停止的评测。')
        with self.lock:
            if body['id'] not in self.jobs:raise NotFound('评测记录不存在。')
            job=self.jobs[body['id']]
            if job['state'] in ('queued','running','cancelling'):
                job['cancel'].set();job['state']='cancelling'
            return self.job(body['id'])

    def close(self):
        with self.lock:
            self.closed=True
            for job in self.jobs.values():job['cancel'].set()
        if self.thread:self.thread.join(timeout=1)

    def handle(self,method,path,query,body):
        action=path.removeprefix('/api/evaluation/')
        if action=='datasets' and method=='GET':return self.datasets(),None
        if action=='datasets' and method=='POST':return self.prepare(body),None
        if action=='labels' and method=='GET':return self.labels(query)
        if action=='labels' and method=='POST':return self.save_label(body),None
        if action=='models' and method=='GET':return self.models(),None
        if action=='reports' and method=='GET':return self.reports(),None
        if action=='report' and method=='GET':return self.report(query.get('id',[''])[0]),'courseinbox-evaluation.json' if query.get('download')==['1'] else None
        if action=='runs' and method=='GET':return self.job(query.get('id',[None])[0]),None
        if action=='runs' and method=='POST':return self.start(body),None
        if action=='cancel' and method=='POST':return self.cancel(body),None
        raise NotFound('评测接口不存在。')
