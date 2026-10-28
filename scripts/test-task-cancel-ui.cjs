'use strict';
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const testServer=createTestServer('courseinbox-task-cancel-');
let browser;
(async()=>{
 const {url,api}=await testServer.start();
 const original=await api('messages',{text:'《撤销验证》实验一，请提交报告和源代码，截止2099年11月20日18:00。',captured_at:'2026-10-23T09:00:00+08:00'});
 let task=await api('proposals/'+original.proposals[0].id+'/confirm',{});
 task=await api('tasks/'+task.id,{status:'in_progress',checklist:task.checklist.map(()=>true),expected_version:task.version},'PATCH');
 const before=await api('tasks/'+task.id);
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(6000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const row=()=>page.locator('.task-row').filter({has:page.locator('[data-status="'+task.id+'"]')});
 await page.goto(url+'/#tasks');
 await row().locator('[data-status]').selectOption('cancelled');await page.locator('#statusConfirmDialog').waitFor();assert.equal((await api('tasks/'+task.id)).version,before.version);await page.locator('#statusConfirmDialog [value="cancel"]').click();assert.equal((await api('tasks/'+task.id)).status,'in_progress');
 await row().locator('[data-status]').selectOption('submitted');await page.locator('#statusConfirmDialog').waitFor();await page.locator('#statusConfirmDialog').press('Escape');assert.equal((await api('tasks/'+task.id)).version,before.version);
 await row().locator('[data-status]').selectOption('cancelled');await page.locator('#statusConfirmDialog [value="confirm"]').click();await row().waitFor({state:'detached'});
 await page.locator('#toast').getByRole('button',{name:'撤销',exact:true}).click();await row().waitFor();assert.equal((await api('tasks/'+task.id)).status,'in_progress');
 // Reload removes ephemeral undo; the cancelled row still provides a durable restore action.
 await row().locator('[data-status]').selectOption('cancelled');await page.locator('#statusConfirmDialog [value="confirm"]').click();await row().waitFor({state:'detached'});await page.reload();await page.locator('#statusFilter').selectOption('all');await row().getByRole('button',{name:'恢复任务',exact:true}).click();await row().locator('[data-status]').filter({visible:true}).waitFor();
 await page.waitForFunction(id=>state.tasks.find(t=>t.id===id)?.status==='in_progress',task.id);assert.equal((await api('tasks/'+task.id)).status,'in_progress');
 // The detail dialog has its own restore button, including after a checklist-only update.
 await row().getByRole('button',{name:'查看详情',exact:true}).click();await page.locator('#detailStatus').selectOption('submitted');await page.locator('#statusConfirmDialog').waitFor();const beforeReturn=await api('tasks/'+task.id);await page.locator('#statusConfirmDialog [value="cancel"]').click();assert.equal((await api('tasks/'+task.id)).version,beforeReturn.version);assert.equal(await page.locator('#detailStatus').inputValue(),'pending');await page.locator('#detailStatus').selectOption('cancelled');await page.locator('#statusConfirmDialog [value="confirm"]').click();await page.locator('#taskDetail [data-restore-task]').waitFor();
 let cancelled=await api('tasks/'+task.id);await api('tasks/'+task.id,{checklist:cancelled.checklist.map(()=>false),expected_version:cancelled.version},'PATCH');
 await page.locator('#taskDetail [data-restore-task]').click();await page.locator('#toast').filter({hasText:'已更新'}).waitFor();assert.equal((await api('tasks/'+task.id)).status,'cancelled','stale restore must not overwrite a newer edit');
 await page.locator('#taskDialog [data-close]').click();await row().getByRole('button',{name:'查看详情',exact:true}).click();await page.locator('#taskDetail [data-restore-task]').click();await page.waitForFunction(()=>document.querySelector('#detailStatus')?.value==='pending');
 task=await api('tasks/'+task.id);assert.equal(task.status,'in_progress');assert(task.checklist.every(x=>!x.done));assert.equal(task.sources.length,before.sources.length);assert.equal(task.deadline,before.deadline);assert.equal(task.title,before.title);
 await page.locator('#taskDialog [data-close]').click();
 for(const status of ['pending','done','submitted']){
   await row().locator('[data-status]').selectOption(status);if(status==='submitted')await page.locator('#statusConfirmDialog [value="confirm"]').click();await page.waitForFunction(({id,status})=>state.tasks.find(t=>t.id===id)?.status===status,{id:task.id,status});
   await row().locator('[data-status]').selectOption('cancelled');await page.locator('#statusConfirmDialog [value="confirm"]').click();await row().getByRole('button',{name:'恢复任务',exact:true}).click();await page.waitForFunction(({id,status})=>state.tasks.find(t=>t.id===id)?.status===status,{id:task.id,status});assert.equal((await api('tasks/'+task.id)).status,status);
 }
 await page.setViewportSize({width:390,height:900});await row().locator('[data-status]').selectOption('cancelled');await page.locator('#statusConfirmDialog [value="confirm"]').click();await page.locator('#toast button').waitFor();
 const dimensions=await page.locator('#toast').evaluate(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,width:innerWidth}));assert(dimensions.left>=0&&dimensions.right<=dimensions.width);
 await page.locator('#toast').getByRole('button',{name:'撤销',exact:true}).click();await page.waitForFunction(id=>state.tasks.find(t=>t.id===id)?.status==='submitted',task.id);
 assert.deepEqual(await page.locator('#statusFilter option').allTextContents(),['尚未提交','全部任务','已逾期','已做完','已提交']);
 await row().locator('[data-status]').selectOption('pending');await page.waitForFunction(id=>state.tasks.find(t=>t.id===id)?.status==='pending',task.id);
 await page.locator('#statusFilter').selectOption('active');await row().locator('[data-status]').selectOption('submitted');await page.locator('#statusConfirmDialog [value="confirm"]').click();await row().waitFor({state:'detached'});
 await page.locator('#toast').getByRole('button',{name:'撤销',exact:true}).click();await row().waitFor();assert.equal((await api('tasks/'+task.id)).status,'pending');
 await row().locator('[data-status]').selectOption('submitted');await page.locator('#statusConfirmDialog [value="confirm"]').click();await row().waitFor({state:'detached'});await page.reload();await page.locator('#statusFilter').selectOption('submitted');
 await row().getByRole('button',{name:'撤销提交',exact:true}).click();await row().waitFor({state:'detached'});assert.equal((await api('tasks/'+task.id)).status,'pending');
 await page.locator('#statusFilter').selectOption('active');await row().getByRole('button',{name:'查看详情',exact:true}).click();await page.locator('#detailStatus').selectOption('submitted');await page.locator('#statusConfirmDialog [value="confirm"]').click();await page.locator('#taskDetail').getByRole('button',{name:'撤销提交',exact:true}).waitFor();
 const submitted=await api('tasks/'+task.id);await api('tasks/'+task.id,{checklist:submitted.checklist.map(()=>true),expected_version:submitted.version},'PATCH');
 await page.locator('#taskDetail').getByRole('button',{name:'撤销提交',exact:true}).click();await page.locator('#toast').filter({hasText:'已更新'}).waitFor();assert.equal((await api('tasks/'+task.id)).status,'submitted');
 await page.locator('#taskDetail').getByRole('button',{name:'撤销提交',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#detailStatus')?.value==='pending');assert.equal((await api('tasks/'+task.id)).status,'pending');
 await page.locator('#detailStatus').selectOption('done');await page.waitForFunction(()=>document.querySelector('#detailStatus')?.value==='done');
 await page.locator('#detailStatus').selectOption('submitted');await page.locator('#statusConfirmDialog [value="confirm"]').click();await page.locator('#taskDetail').getByRole('button',{name:'撤销提交',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#detailStatus')?.value==='done');assert.equal((await api('tasks/'+task.id)).status,'done');
 assert.deepEqual(errors,[]);console.log('PASS cancelled/submitted undo: immediate and after reload, row/detail restore, previous pending/done status, checklist/source retained, stale version rejected, compact filters retained');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await testServer.close()}});
