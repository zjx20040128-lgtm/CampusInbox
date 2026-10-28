'use strict';
const assert=require('node:assert/strict'),{spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const server=createTestServer('checkin-update-');let browser;
(async()=>{
const seed=`from pathlib import Path
import sys
from courseinbox.core import Inbox
from courseinbox.chaoxing import ingest_web_message
box=Inbox(Path(sys.argv[1])/'inbox.sqlite3')
r=ingest_web_message(box,dict(message_id='chat-sign',text='位置签到',conversation='示例课程',captured_at='2026-10-20T13:12:00+08:00',direction='received'))
from unittest.mock import patch
# Legacy unknown-deadline task, created before the new guard.
with patch('courseinbox.checkin_evidence.verification',return_value='verified'):
 t=box.confirm(r['proposals'][0]['id'])
ingest_web_message(box,dict(kind='checkin_activity',message_id='checkin-1',text='位置签到',title='位置签到',conversation='示例课程',captured_at='2026-10-20T13:12:31+08:00',published_at='2026-10-20T13:12:31+08:00',deadline='2026-10-20T13:42:31+08:00',activity_id='123',course_id='456',class_id='789',field_evidence={'deadline':'学习通签到活动结束时间：2026-10-20 13:42:31'}))
`;
const r=spawnSync(server.python,['-B','-X','utf8','-c',seed,server.directory],{cwd:server.root,encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);
const {url}=await server.start();browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();
await page.goto(url+'/#inbox');const card=page.locator('.proposal').filter({hasText:'位置签到'});const confirm=page.getByRole('button',{name:'确认变更',exact:true});await confirm.waitFor();assert.equal(await page.locator('.duplicate-review').count(),0);assert(await confirm.isEnabled());await confirm.click();
await page.waitForFunction(()=>!document.querySelector('[data-confirm]'));
const token=(await(await page.request.get(url+'/api/bootstrap')).json()).token;
const tasks=await(await page.request.get(url+'/api/tasks',{headers:{Authorization:'Bearer '+token}})).json();assert.equal(tasks.length,1);assert.equal(tasks[0].deadline,'2026-10-20T13:42:31+08:00');
const access=require('node:crypto').createHmac('sha256',token).update('courseinbox:chaoxing-web:v1').digest('hex');
const post=async body=>{const r=await page.request.post(url+'/api/chaoxing/messages',{headers:{Authorization:'Bearer '+access},data:body});assert(r.ok(),await r.text())};
await post({message_id:'expired-chat',text:'位置签到',conversation:'另一场签到',captured_at:'2026-10-20T16:26:00+08:00',direction:'received'});
await page.reload();await page.getByRole('button',{name:'等待核验签到',exact:true}).waitFor();assert(await page.getByRole('button',{name:'等待核验签到',exact:true}).isDisabled());
await post({kind:'checkin_activity',message_id:'expired-detail',text:'位置签到',title:'位置签到',conversation:'另一场签到',captured_at:'2026-10-20T16:26:28+08:00',published_at:'2026-10-20T16:26:28+08:00',deadline:'2026-10-20T16:56:28+08:00',activity_id:'999',course_id:'456',class_id:'789',field_evidence:{deadline:'学习通签到活动结束时间：2026-10-20 16:56:28'}});
await page.reload();await page.getByRole('button',{name:'签到已结束',exact:true}).waitFor();assert(await page.getByRole('button',{name:'签到已结束',exact:true}).isDisabled());
const current=await(await page.request.get(url+'/api/state',{headers:{Authorization:'Bearer '+token}})).json();
const expired=current.proposals.find(p=>p.checkin_expired);assert(expired);assert.equal(expired.candidate.deadline,'2026-10-20T16:56:28+08:00');
const blocked=await page.request.post(url+'/api/proposals/'+expired.id+'/confirm',{headers:{Authorization:'Bearer '+token},data:{}});assert.equal(blocked.status(),409);
await post({message_id:'custom-card',text:'周二课堂签到',activity_type:'checkin',conversation:'自定义签到课程',captured_at:'2026-10-20T17:26:00+08:00',direction:'received'});
let snapshot=await(await page.request.get(url+'/api/state',{headers:{Authorization:'Bearer '+token}})).json();
const custom=snapshot.proposals.find(p=>p.candidate.title==='周二课堂签到');assert(custom?.checkin_unverified);
const supplement=await page.request.post(url+'/api/messages/'+custom.message_id+'/supplements',{headers:{Authorization:'Bearer '+token},data:{text:'截止时间：2099年1月1日18:00',target:'proposal:'+custom.id}});assert(supplement.ok(),await supplement.text());
const supplemented=await supplement.json();const supplementedId=supplemented.proposals[0].id;
const bypass=await page.request.post(url+'/api/proposals/'+supplementedId+'/confirm',{headers:{Authorization:'Bearer '+token},data:{}});assert.equal(bypass.status(),409);
await post({kind:'checkin_activity',message_id:'custom-valid',text:'周二课堂签到',title:'周二课堂签到',conversation:'自定义签到课程',captured_at:'2026-10-20T17:26:28+08:00',published_at:'2026-10-20T17:26:28+08:00',deadline:'2099-01-01T18:00:00+08:00',activity_id:'1000',course_id:'456',class_id:'789',field_evidence:{deadline:'学习通签到活动结束时间：2099-01-01 18:00'}});
await post({kind:'checkin_activity',message_id:'custom-ended',text:'周二课堂签到',title:'周二课堂签到',conversation:'自定义签到课程',captured_at:'2026-10-20T17:26:28+08:00',published_at:'2026-10-20T17:26:28+08:00',deadline:null,activity_state:'ended',activity_id:'1001',course_id:'456',class_id:'789',field_evidence:{activity_state:'已结束'}});
await page.reload();await page.getByRole('button',{name:'先核对签到场次',exact:true}).waitFor();assert(await page.getByRole('button',{name:'先核对签到场次',exact:true}).isDisabled());
const ambiguous=await page.request.post(url+'/api/proposals/'+supplementedId+'/confirm',{headers:{Authorization:'Bearer '+token},data:{}});assert.equal(ambiguous.status(),409);
await page.goto('about:blank');await page.goto(url+'/#tasks');await page.locator('#statusFilter').selectOption('all');
const oldRow=page.locator('.task-row').filter({has:page.locator(`[data-detail="${tasks[0].id}"]`)});
assert((await oldRow.innerText()).includes('签到已结束'),'overdue formatting must not hide the ended sign-in label');
console.log('PASS sign-in deadline update enabled, human confirmation updates original task without duplicates');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await server.close()}});
