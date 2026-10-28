"""Prospective local holdout preparation and paired automatic-output comparison."""
import hashlib
import json
from pathlib import Path
from .core import ValidationError, normalize, now_iso
from .evaluation import _messages, _key, validate_labels
from .task_identity import platform_identity


def prepare_holdout(database, directory, excluded_paths=()):
    messages=[m for m in _messages(database) if not m.get('sample')]
    excluded=set()
    for path in excluded_paths:
        rows,_=validate_labels(json.loads(Path(path).read_text(encoding='utf-8-sig')))
        excluded.update(r['key'] for r in rows)
    def keys(m):
        result={_key(m)}
        external=m.get('external',{})
        if external.get('kind')=='course_notice' and external.get('message_id'):
            result.add(hashlib.sha256(external['message_id'].encode()).hexdigest()[:16])
        return result
    parents={m['id']:m['id'] for m in messages};tokens={}
    def find(key):
        while parents[key]!=key:
            parents[key]=parents[parents[key]];key=parents[key]
        return key
    for m in messages:
        external=m.get('external',{})
        identities=['text:'+normalize(m['text'])]
        identity=platform_identity(external.get('url',''))
        if identity:identities.append('platform:'+identity)
        if external.get('kind')=='course_notice' and external.get('message_id'):
            identities.append('notice:'+external['message_id'])
        for identity in identities:
            if identity in tokens:parents[find(m['id'])]=find(tokens[identity])
            else:tokens[identity]=m['id']
    def group(m):return hashlib.sha256(find(m['id']).encode()).hexdigest()
    # Same body across courses is a single group. Excluding any previously used
    # notice excludes all its duplicates, not merely its current database id.
    excluded_groups={group(m) for m in messages if keys(m)&excluded}
    groups={}
    for m in messages:
        if group(m) not in excluded_groups:groups.setdefault(group(m),[]).append(m)
    ordered=sorted(groups)
    holdout=set(ordered[::5])
    rows=[]
    for g in ordered:
        # Keep distinct revisions, but only one copy of an identical body.
        representatives={}
        for m in sorted(groups[g],key=_key):representatives.setdefault(normalize(m['text']),m)
        for m in representatives.values():
            external=m.get('external',{})
            published=external.get('published_at') if external.get('kind')=='task_center' else (None if external.get('time_known') is False else m.get('captured_at'))
            rows.append(dict(key=_key(m),group=g,split='holdout' if g in holdout else 'development',reviewed=False,
                expected_tasks=[],review_text=m['text'],review_course=m.get('course',''),review_scope=m.get('scope',''),
                review_published_at=published,source_kind=external.get('kind','manual')))
    value=dict(schema=2,prepared_at=now_iso(),origin='prospective_local_holdout',
        instructions='逐条人工核对原文后填写 expected_tasks，再设置 reviewed=true。普通通知填空数组。development 用于修改规则和提示词；holdout 仅用于最终比较，查看错误并调参后应换新留出集。此划分不能证明历史上从未接触过这些原文。',labels=rows)
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'labels.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    holdout_rows=sum(r['split']=='holdout' for r in rows)
    return dict(prepared=len(rows),development=len(rows)-holdout_rows,holdout=holdout_rows,reviewed=0,
        excluded_groups=len(excluded_groups),deduplicated=sum(len(v) for v in groups.values())-len(rows),
        historical_contamination='unknown',labels=str(directory/'labels.json'))


def compare_reports(rules,hybrid):
    left={r['key']:r for r in rules['cases']};right={r['key']:r for r in hybrid['cases']}
    if left.keys()!=right.keys():raise ValidationError('只能比较同一组通知。')
    def errors(row):
        return (row['expected']-row['matched']+row['predicted']-row['matched']+
            row.get('deadline_cases',0)-row.get('deadline_right',0)+row.get('unsupported_deadlines',0)+
            row.get('operation_cases',0)-row.get('operation_right',0))
    wins=losses=ties=0;before=after=0
    for key in left:
        if left[key]['status']!='evaluated' or right[key]['status']!='evaluated':
            return dict(outcome='inconclusive',reason='存在缺失或失败样本，不能判定优劣。')
        a,b=errors(left[key]),errors(right[key]);before+=a;after+=b
        wins+=b<a;losses+=b>a;ties+=b==a
    unreliable=any(hybrid.get(k,0) or rules.get(k,0) for k in ('errors','model_fallbacks','limited'))
    outcome='inconclusive' if unreliable or not left else 'hybrid_better' if after<before else 'hybrid_worse' if after>before else 'tie'
    return dict(outcome=outcome,paired_cases=len(left),hybrid_wins=wins,hybrid_losses=losses,ties=ties,
        rule_field_errors=before,hybrid_field_errors=after,
        scope='比较自动输出中的漏报、误报、截止错误和操作错误；人工确认不计入模型准确率。仅代表当前样本，不代表统计显著或一般准确率。')
