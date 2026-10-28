'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {spawnSync}=require('child_process'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const testServer=createTestServer('courseinbox-identity-');
const {root,directory,python}=testServer;
let browser;
(async()=>{
 const seed=`import sys,json
from pathlib import Path
from courseinbox.core import Inbox
box=Inbox(Path(sys.argv[1])/'inbox.sqlite3')
def capture(title,course,scope,url='',deadline='2030-10-30',source='学习通课程通知'):
 text=title+'；请提交实验报告。'
 c=dict(title=title,course=course,scope=scope,kind='assignment',operation='create',deadline=deadline,requirements=['实验报告'],matchable=True,source_url=url,evidence=text)
 return box.ingest(text,source=source,captured_at='2026-10-17T12:00:00+08:00',course=course,scope=scope,candidates=[c])
first=capture('目标检测编程实践','人工智能','一班');task=box.confirm(first['proposals'][0]['id'])
review=capture('目标检测编程实践（作业）','人工智能','一班',deadline='2030-11-01')
url='https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=3&classId=4&workId=99'
a=capture('实验三','数据库','一班',url)
b=capture('实验三','数据库','数据库',url+'&enc=new',source='学习通作业中心')
assert a['proposals'][0]['id']==b['proposals'][0]['id']
(Path(sys.argv[1])/'seed.json').write_text(json.dumps(dict(task=task['id'],review=review['proposals'][0]['id'],group=a['proposals'][0]['id'])),encoding='utf-8')
`;
 const seeded=spawnSync(python,['-B','-X','utf8','-c',seed,directory],{cwd:root,encoding:'utf8',windowsHide:true});
 assert.equal(seeded.status,0,seeded.stderr);const fixture=JSON.parse(fs.readFileSync(path.join(directory,'seed.json'),'utf8'));
 const {url}=await testServer.start();
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();page.setDefaultTimeout(6000);
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const token=(await(await page.request.get(url+'/api/bootstrap')).json()).token,headers={Authorization:'Bearer '+token};
 const rejected=await page.request.post(url+'/api/proposals/'+fixture.review+'/confirm',{headers,data:{}});assert.equal(rejected.status(),409);
 await page.goto(url+'/#inbox');
 const card=page.locator('[data-proposal="'+fixture.review+'"]');await card.locator('.duplicate-review').waitFor();
 assert.equal(await card.locator('[data-confirm]').isDisabled(),true);
 await card.getByRole('button',{name:'查看已有任务'}).click();await page.locator('#taskDialog').waitFor({state:'visible'});
 await page.locator('#taskDialog [data-close]').click();
 await card.getByRole('button',{name:'仅关联原文'}).click();await card.waitFor({state:'detached'});
 const detail=await(await page.request.get(url+'/api/tasks/'+fixture.task,{headers})).json();
 assert.equal(detail.deadline,'2030-10-30');assert.equal(detail.status,'pending');assert.equal(detail.sources.length,2);
 const group=page.locator('[data-proposal="'+fixture.group+'"]');await group.getByText('已合并 2 份相同候选来源',{exact:true}).waitFor();
 await group.locator('.proposal-source-group summary').click();assert.equal(await group.locator('[data-message-detail]').count(),2);
 await group.getByRole('button',{name:'查看来源 2'}).click();await page.locator('#messageDialog').waitFor({state:'visible'});await page.locator('#messageDialog [data-close]').click();
 await group.locator('[data-confirm]').click();await group.waitFor({state:'detached'});
 const state=await(await page.request.get(url+'/api/state',{headers})).json();assert.equal(state.tasks.length,2);
 const grouped=state.tasks.find(t=>t.course==='数据库'),groupDetail=await(await page.request.get(url+'/api/tasks/'+grouped.id,{headers})).json();assert.equal(groupDetail.sources.length,2);
 assert.deepEqual(errors,[]);
 console.log('PASS identity review blocks copies, explicit source-only linking preserves fields, equivalent drafts retain all sources; consoleErrors=[]');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await testServer.close()}});
