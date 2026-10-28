 'use strict';
const assert=require('node:assert/strict'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const server=createTestServer('campusinbox-polish-');let browser;
(async()=>{
 const {url,api}=await server.start();browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'/#tasks');await page.locator('#deadlineFilter').waitFor();
 await page.evaluate(()=>{
   const today=cnLocalTime().slice(0,10),next=cnLocalTime(new Date(Date.now()+86400000)).slice(0,10);
   state.tasks=[{id:'one',title:'今日报告',course:'课程甲',scope:'甲班',kind:'assignment',status:'pending',deadline:today},
    {id:'two',title:'明日报告',course:'课程乙',scope:'乙班',kind:'assignment',status:'pending',deadline:next},
    {id:'three',title:'未定报告',course:'课程甲',scope:'甲班',kind:'assignment',status:'pending',deadline:null}];
   filters.course='';filters.search='';filters.status='all';filters.deadline='all';renderTasks();
 });
 await page.locator('#deadlineFilter').selectOption('today');assert.equal(await page.locator('.task-row').count(),1);
 assert.match(await page.locator('#taskResults').innerText(),/1 \/ 3/);
 await page.locator('#courseFilter').selectOption('课程乙');assert.equal(await page.locator('.task-row').count(),0);
 await page.locator('#deadlineFilter').selectOption('week');assert.equal(await page.locator('.task-row').count(),1);
 await page.locator('#courseFilter').selectOption('');await page.locator('#deadlineFilter').selectOption('unknown');
 assert.deepEqual(await page.locator('.task-row h3').allTextContents(),['未定报告']);
 assert.equal(await page.evaluate(()=>taskMatchesDeadline({deadline:'2027-01-01T00:30:00+08:00'},'week',new Date('2026-12-30T12:00:00+08:00'))),true);
 assert.equal(await page.evaluate(()=>taskMatchesDeadline({deadline:'2026-12-29T17:00:00Z'},'today',new Date('2026-12-30T12:00:00+08:00'))),true);
 assert.equal(await page.evaluate(()=>taskMatchesDeadline({deadline:null},'month')),false);
 for(const width of [1440,390,320]){
  await page.setViewportSize({width,height:1000});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 }
 await page.locator('#deadlineFilter').selectOption('all');
 await page.locator('#taskDeadlineFrom').fill('2099-01-01');await page.locator('#taskDeadlineTo').fill('2099-01-31');await page.locator('#taskDeadlineSearch').click();assert.equal(await page.locator('.task-row').count(),0);
 await page.locator('#taskDeadlineReset').click();assert.equal(await page.locator('.task-row').count(),3);
 await api('messages',{text:'《范围查询》作业一，截止2026年11月1日20:00。',captured_at:'2026-10-26T12:00:00+08:00',mode:'rules'});
 await api('messages',{text:'《范围查询》作业二，截止2026年10月30日20:00。',captured_at:'2026-10-26T12:00:00+08:00',mode:'rules'});
 const invalid=await page.request.get(url+'/api/messages/page?deadline_from=2026-02-30',{headers:{Authorization:'Bearer '+(await (await page.request.get(url+'/api/bootstrap')).json()).token}});assert.equal(invalid.status(),400);
 await page.goto(url+'/?deadline-query#inbox');await page.locator('[data-inbox-tab="messages"]').click();await page.locator('.message-card').first().waitFor();
 await page.locator('#messageDeadlineFrom').fill('2026-11-01');await page.locator('#messageDeadlineTo').fill('2026-11-30');await page.locator('#messageDeadlineSearch').click();
 await page.waitForFunction(()=>document.querySelectorAll('.message-card').length===1);
 assert.match(await page.locator('.message-card').innerText(),/作业一/);assert.equal(await page.locator('#clearAllMessages').isVisible(),false);
 await page.locator('#messageDeadlineReset').click();await page.waitForFunction(()=>document.querySelectorAll('.message-card').length===2);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 await page.goto(url+'/?mobile-polish#mobile');await page.locator('#wechatPushSave:not([disabled])').waitFor();
 assert.equal(await page.locator('#wechatPush').isVisible(),true);
 assert.equal(await page.locator('.browser-reminder-options').getAttribute('open'),null);
 assert.equal(await page.locator('#mobileRemindersToggle').isVisible(),false);
 await page.locator('.browser-reminder-options>summary').click();assert.equal(await page.locator('#mobileRemindersToggle').isVisible(),true);
 assert.deepEqual(errors,[]);console.log('PASS combined date/course/status filters, unknown/date-only/CN timezone/year boundary, result count, 320px and collapsed backup connection');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await server.close()}});
