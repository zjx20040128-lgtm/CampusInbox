"""Read-only desktop readiness evidence; never substitutes for human acceptance."""
import json
from .core import now_iso


def desktop_acceptance_report(inbox,sync_status,agent_info,inventory=None):
    raw=inventory or {}
    def count(value):return value if type(value) is int and value>=0 else 0
    inventory_summary=dict(available=bool(raw.get('catalog_at')),catalog_limited=raw.get('catalog_limited') is not False,
                           total=count(raw.get('total')),unchecked_sections=count(raw.get('unchecked_sections')),
                           detail_pending=count(raw.get('detail_pending')),manual_details=count(raw.get('manual_details')),
                           deadline_pending=count(raw.get('deadline_pending')),
                           counts={key:count(raw.get('counts',{}).get(key)) for key in ('missing','unrecognized','pending','confirmed','archived','ignored','cleared')})
    sources={}
    states={'idle','connecting','waiting_scan','connected','syncing','expired','paused','error','retrying','partial'}
    for name in ('chat','notice','task_center'):
        value=sync_status.get('sources',{}).get(name,{})
        sources[name]={key:max(0,value.get(key,0)) if type(value.get(key,0)) is int else 0 for key in ('checked_count','captured_count','failed_count','pending_count','detail_pending_count','unsupported_detail_count','media_pending_count','attachment_pending_count')}
        sources[name].update(state=value.get('state') if value.get('state') in states else 'unknown',coverage=value.get('coverage') if value.get('coverage') in {'unknown','loaded_text','partial','list_only','complete'} else 'unknown',freshness=value.get('freshness') if value.get('freshness') in {'fresh','starting','stale','paused','offline'} else 'unknown',has_complete_check=bool(value.get('last_complete_success')))
    with inbox.connection() as db:
        db.execute('BEGIN')
        counts={name:db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('messages','proposals','sources','history')}
        tasks=[json.loads(row['data']) for row in db.execute('SELECT data FROM tasks')]
        active=[task for task in tasks if not task.get('merged_into')];counts['tasks']=len(active)
        owners={};conflicting=set()
        for task in active:
            for identity in inbox._task_platform_identities(db,task):
                if identity in owners and owners[identity]!=task['id']:conflicting.add(identity)
                owners[identity]=task['id']
        integrity=db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        alert_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='desktop_alert_settings'").fetchone()
        enabled=db.execute("SELECT data FROM desktop_alert_settings WHERE key='enabled'").fetchone() if alert_table else None
        reminder_enabled=json.loads(enabled['data']) if enabled else True
    checks=[dict(id='worker',status='pass' if sync_status.get('enabled') and sync_status.get('worker_alive') and sync_status.get('freshness')=='fresh' else 'pending'),
            dict(id='queue',status='pass' if sync_status.get('queued',0)==0 and sync_status.get('incomplete',0)==0 else 'pending'),
            dict(id='database',status='pass' if integrity and not conflicting else 'fail'),
            dict(id='reminder_enabled',status='pass' if reminder_enabled else 'pending')]
    for name,value in sources.items():
        ready=value['state']=='connected' and value['coverage']=='complete' and value['freshness']=='fresh' and value['has_complete_check'] and not any(value[key] for key in ('failed_count','pending_count','detail_pending_count','unsupported_detail_count','media_pending_count','attachment_pending_count'))
        checks.append(dict(id=name,status='pass' if ready else 'pending'))
    inventory_ready=(inventory_summary['available'] and not inventory_summary['catalog_limited'] and
                     not any(inventory_summary[key] for key in ('unchecked_sections','detail_pending','manual_details','deadline_pending')) and
                     not any(inventory_summary['counts'][key] for key in ('missing','unrecognized')))
    checks.append(dict(id='inventory',status='pass' if inventory_ready else 'pending'))
    manual=[('platform_release','用独立发布与学生账号确认新作业可见，并核对采集原文。'),('task_changes','核对延期、取消、重复发布、冲突、提交和退回全流程。'),('image_attachment','对照原图片和附件核对识别文字及遗漏。'),('windows_notification','实际观察 Windows 通知显示和点击定位。'),('sleep_restart','实测关闭网页、断网、休眠及重启后的恢复。')]
    return dict(schema_version=2,generated_at=now_iso(),automated_ready=all(item['status']=='pass' for item in checks),real_acceptance='pending',checks=checks,sources=sources,inventory=inventory_summary,counts=counts,duplicate_platform_identities=len(conflicting),model_assistance_configured=agent_info.get('mode')=='agent',manual_checks=[dict(id=key,status='pending',instruction=text) for key,text in manual],scope='本机只读检查；不含消息正文、账号凭据或学习通链接。自动检查不能证明真实发布、模型准确率或系统通知显示。')
