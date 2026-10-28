"""Evaluate reviewed local notices without changing source data or model settings."""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from courseinbox.core import Inbox, ValidationError, now_iso
from courseinbox.evaluation import evaluate as run_evaluation, prepare_labels, local_provider, model_runner
from courseinbox.agent import AgentError
from courseinbox.benchmark import prepare_holdout, compare_reports


def load_model_environment():
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip() in {'CI_MODEL_PROVIDER','CI_MODEL_BASE_URL','CI_MODEL'}:
                os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))


def ollama_data(base_url, endpoint):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base_url.rstrip('/') + endpoint,timeout=5) as response:
        raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValidationError('本机模型列表过大。')
        return json.loads(raw)


def evaluate(mode, database, labels_path, limit=0, model=None, base_url=None, split=None):
    """Preserve the previous script's callable entry point."""
    if mode=='rules':
        return run_evaluation(database,labels_path,limit=limit,split=split)
    if mode!='qwen':raise ValidationError('评测模式无效。')
    provider=local_provider(base_url or os.environ.get('CI_MODEL_BASE_URL','http://127.0.0.1:11434'),model or os.environ.get('CI_MODEL',''))
    with tempfile.TemporaryDirectory(prefix='courseinbox-evaluation-') as directory:
        box=Inbox(Path(directory)/'context.sqlite3')
        return run_evaluation(database,labels_path,mode='qwen',model=provider.model,runner=model_runner(box,provider),limit=limit,split=split)


def main():
    parser=argparse.ArgumentParser(description='电脑端本地通知评测与人工标注准备')
    parser.add_argument('--mode',choices=['rules','qwen','compare'],default='rules')
    parser.add_argument('--database',type=Path,default=ROOT/'data/inbox.sqlite3')
    parser.add_argument('--labels',type=Path,default=ROOT/'data/verification/real-notice-labels.json')
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--models',nargs='+',help='仅比较本机已经安装的 Ollama 模型，不下载、不改配置')
    parser.add_argument('--base-url',default=None)
    parser.add_argument('--prepare',type=Path,help='创建含本机原文的待人工标注JSON，不覆盖已有文件')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--prepare-holdout',type=Path,help='新建开发/留出标注目录，不覆盖已有目录')
    parser.add_argument('--exclude-labels',type=Path,nargs='*',help='排除已用于调参的人工标注；默认排除旧版真实通知评测集')
    parser.add_argument('--split',choices=['development','holdout'],help='只评测所选分组内人工核对的通知')
    args=parser.parse_args()
    load_model_environment()
    try:
        if args.output and args.output.resolve() in (args.database.resolve(),args.labels.resolve()):
            raise ValidationError('报告不能覆盖数据库或人工标注文件。')
        if args.prepare and args.prepare_holdout:raise ValidationError('请选择一种标注准备方式。')
        if args.prepare_holdout:
            exclusions=args.exclude_labels if args.exclude_labels is not None else [ROOT/'data/verification/real-notice-labels.json']
            result=prepare_holdout(args.database,args.prepare_holdout,exclusions)
        elif args.prepare:
            result=prepare_labels(args.database,args.prepare,limit=args.limit or 200)
        elif args.mode=='compare':
            base=args.base_url or os.environ.get('CI_MODEL_BASE_URL','http://127.0.0.1:11434')
            models=list(dict.fromkeys(args.models or [os.environ.get('CI_MODEL','')]))
            if any(not model for model in models):raise ValidationError('请用 --models 指定本机已安装的模型名称。')
            for model in models:local_provider(base,model)
            installed={m.get('name') for m in ollama_data(base,'/api/tags').get('models',[])}
            with tempfile.TemporaryDirectory(prefix='courseinbox-comparison-') as directory:
                snapshot=Path(directory)/'snapshot.sqlite3'
                with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
                result=dict(schema_version=1,generated_at=now_iso(),database_snapshot='shared_readonly_copy',runs=[evaluate('rules',snapshot,args.labels,args.limit,split=args.split)],comparisons=[])
                for model in models:
                    if model not in installed:
                        result['runs'].append(dict(mode='qwen',model=model,status='not_installed'))
                        continue
                    report=evaluate('qwen',snapshot,args.labels,args.limit,model,base,split=args.split)
                    try:
                        processes=ollama_data(base,'/api/ps').get('models',[])
                        report['loaded_model_snapshot']=[{key:value[key] for key in ('size','size_vram') if type(value.get(key)) is int} for value in processes if value.get('name')==model]
                    except (OSError,ValueError):report['loaded_model_snapshot']=None
                    report['resource_scope']='Ollama运行后模型内存/显存快照（字节），不是整机峰值或16GB运行验收。'
                    result['runs'].append(report)
                    result['comparisons'].append(dict(model=model,**compare_reports(result['runs'][0],report)))
        else:
            if args.models and len(args.models)!=1:raise ValidationError('多个模型请使用 --mode compare。')
            result=evaluate(args.mode,args.database,args.labels,args.limit,(args.models or [None])[0],args.base_url,split=args.split)
        serialized=json.dumps(result,ensure_ascii=False,indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(serialized+'\n',encoding='utf-8')
        print(serialized)
        return 0
    except (OSError,ValueError,KeyError,sqlite3.Error,AgentError) as error:
        print(json.dumps(dict(error='评测未完成，请核对本机数据库、标注文件及已安装的本地模型。',error_type=type(error).__name__),ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
