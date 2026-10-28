import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from courseinbox.core import Inbox, ValidationError
from courseinbox.evaluation import evaluate
from courseinbox.benchmark import prepare_holdout, compare_reports


class BenchmarkTests(unittest.TestCase):
    def test_partition_groups_duplicates_excludes_used_labels_and_never_labels_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);box=Inbox(root/'source.sqlite3')
            for i in range(24):
                box.ingest(f'实验{i}：请提交报告。',course='课程甲',captured_at='2026-10-20T12:00:00+08:00',candidates=[])
            duplicate=box.ingest('实验1：请提交报告。',course='课程乙',captured_at='2026-10-20T12:00:00+08:00',candidates=[])['message']
            used=root/'used.json'
            used.write_text(json.dumps(dict(schema=2,labels=[dict(key=hashlib.sha256(duplicate['id'].encode()).hexdigest()[:24],reviewed=True,expected_tasks=[])])),encoding='utf-8')
            before=(root/'source.sqlite3').read_bytes()
            prepare_holdout(root/'source.sqlite3',root/'a',[used])
            prepare_holdout(root/'source.sqlite3',root/'b',[used])
            value=json.loads((root/'a/labels.json').read_text(encoding='utf-8'))
            rows=value['labels']
            self.assertEqual(len(rows),23)
            self.assertEqual({r['split'] for r in rows},{'development','holdout'})
            self.assertTrue(all(not r['reviewed'] and r['expected_tasks']==[] for r in rows))
            self.assertEqual([(r['key'],r['split']) for r in rows],[(r['key'],r['split']) for r in json.loads((root/'b/labels.json').read_text(encoding='utf-8'))['labels']])
            self.assertNotIn('实验1：请提交报告。',[r['review_text'] for r in rows])
            self.assertEqual((root/'source.sqlite3').read_bytes(),before)
            with self.assertRaises(FileExistsError):prepare_holdout(root/'source.sqlite3',root/'a',[used])

    def test_selected_holdout_excludes_development_and_unreviewed_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);box=Inbox(root/'db.sqlite3');rows=[]
            for i,split,reviewed in [(1,'development',True),(2,'holdout',True),(3,'holdout',False)]:
                m=box.ingest(f'通知{i}',candidates=[])['message']
                rows.append(dict(key=hashlib.sha256(m['id'].encode()).hexdigest()[:24],split=split,reviewed=reviewed,expected_tasks=[]))
            labels=root/'labels.json';labels.write_text(json.dumps(dict(schema=2,labels=rows)),encoding='utf-8')
            result=evaluate(root/'db.sqlite3',labels,split='holdout')
            self.assertEqual((result['labeled'],result['unreviewed']),(1,1))
            self.assertEqual(result['evaluation_split'],'holdout')
            with self.assertRaises(ValidationError):evaluate(root/'db.sqlite3',labels,split='typo')

    def test_same_platform_task_revisions_stay_in_one_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);box=Inbox(root/'db.sqlite3')
            for i in range(2):
                m=box.ingest(f'实验一第{i}版：请提交报告。',candidates=[])['message']
                m['external']=dict(kind='task_center',url='https://mooc1.chaoxing.com/mooc2/work/task?courseId=1&classId=2&workId=3')
                with box.connection() as db:db.execute('UPDATE messages SET data=? WHERE id=?',(json.dumps(m),m['id']))
            prepare_holdout(root/'db.sqlite3',root/'out')
            rows=json.loads((root/'out/labels.json').read_text(encoding='utf-8'))['labels']
            self.assertEqual(len({r['group'] for r in rows}),1)
            self.assertEqual(len({r['split'] for r in rows}),1)
            self.assertEqual(len(rows),2,'different revisions remain available for annotation')

    def test_comparison_refuses_unpaired_cases_and_does_not_claim_superiority_on_tie(self):
        rule=dict(mode='rules',cases=[dict(key='a',status='evaluated',expected=1,predicted=1,matched=1,deadline_cases=1,deadline_right=1,operation_cases=1,operation_right=1)],errors=0,model_fallbacks=0,limited=0)
        hybrid=dict(rule,mode='qwen')
        self.assertEqual(compare_reports(rule,hybrid)['outcome'],'tie')
        bad=dict(hybrid,cases=[dict(rule['cases'][0],deadline_right=0)])
        self.assertEqual(compare_reports(rule,bad)['outcome'],'hybrid_worse')
        with self.assertRaises(ValidationError):compare_reports(rule,dict(hybrid,cases=[]))
