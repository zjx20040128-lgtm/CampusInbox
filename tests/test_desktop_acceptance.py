import json
import tempfile
import unittest
from pathlib import Path

from courseinbox.core import Inbox


class DesktopAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Inbox(Path(self.tmp.name)/'inbox.sqlite3')

    def report(self,status):
        from courseinbox.acceptance import desktop_acceptance_report
        return desktop_acceptance_report(self.box,status,dict(mode='rules',provider='rules',model=''),self.inventory())

    def inventory(self, **changes):
        value=dict(catalog_at='2026-10-20T12:00:00+08:00',catalog_limited=False,total=1,counts=dict(missing=0,unrecognized=0,pending=1,confirmed=0,archived=0,ignored=0,cleared=0),sections=[dict(state='checked',freshness='fresh')],unchecked_sections=0,detail_pending=0,manual_details=0)
        value.update(changes)
        return value

    def test_inventory_gaps_block_ready_even_when_worker_reports_complete(self):
        from courseinbox.acceptance import desktop_acceptance_report
        for change in (dict(catalog_limited=True),dict(unchecked_sections=1),dict(detail_pending=1),dict(manual_details=1),dict(deadline_pending=1),dict(counts=dict(missing=1)),dict(counts=dict(unrecognized=1)),dict(catalog_at=None)):
            with self.subTest(change=change):
                result=desktop_acceptance_report(self.box,self.ready(),{},self.inventory(**change))
                self.assertFalse(result['automated_ready'])
                self.assertEqual(next(x['status'] for x in result['checks'] if x['id']=='inventory'),'pending')

    def test_unavailable_inventory_does_not_claim_ready(self):
        from courseinbox.acceptance import desktop_acceptance_report
        self.assertFalse(desktop_acceptance_report(self.box,self.ready(),{})['automated_ready'])

    def test_inventory_report_uses_full_counts_and_never_exports_titles(self):
        from courseinbox.acceptance import desktop_acceptance_report
        inventory=self.inventory(total=31,counts=dict(missing=30,pending=1))
        inventory.update(items=[dict(title='private-title',key='private-identity')],sections=[dict(course='private-course',key='private-section')])
        result=desktop_acceptance_report(self.box,self.ready(),{},inventory)
        self.assertEqual(result['inventory']['total'],31)
        self.assertEqual(result['inventory']['counts']['missing'],30)
        for text in ('private-title','private-identity','private-course','private-section'):
            self.assertNotIn(text,json.dumps(result))

    def ready(self):
        return dict(enabled=True,worker_alive=True,queued=0,incomplete=0,freshness='fresh',sources={name:dict(state='connected',coverage='complete',freshness='fresh',last_complete_success='2026-10-17T12:00:00+08:00') for name in ('chat','notice','task_center')})

    def test_complete_intake_does_not_claim_real_publication_or_windows_acceptance(self):
        result=self.report(self.ready())
        self.assertTrue(result['automated_ready']);self.assertEqual(result['real_acceptance'],'pending')
        self.assertTrue(all(item['status']=='pending' for item in result['manual_checks']))
        self.assertIn('windows_notification',[item['id'] for item in result['manual_checks']])

    def test_pending_media_and_stale_source_block_readiness(self):
        status=self.ready();status['incomplete']=1;status['sources']['notice']['media_pending_count']=1
        status['sources']['chat']['freshness']='stale'
        result=self.report(status)
        self.assertFalse(result['automated_ready'])
        self.assertEqual(result['sources']['notice']['media_pending_count'],1)

    def test_report_is_read_only_and_excludes_credentials_urls_and_message_text(self):
        self.box.ingest('private message contents',candidates=[])
        status=self.ready();status.update(cookie='private-cookie',url='https://example.invalid/?token=secret')
        status['sources']['notice']['error']='private-cookie'
        with self.box.connection() as db:before={r['name']:db.execute('SELECT * FROM '+r['name']).fetchall() for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        result=self.report(status);serialized=json.dumps(result)
        for private in ('private-cookie','private message contents','example.invalid','secret'):self.assertNotIn(private,serialized)
        with self.box.connection() as db:after={name:db.execute('SELECT * FROM '+name).fetchall() for name in before}
        self.assertEqual(before,after);self.assertEqual(result['counts']['messages'],1)


if __name__=='__main__':unittest.main()
