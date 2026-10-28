'use strict';
const assert=require('node:assert/strict');
const {TaskCenterCollector}=require('../desktop-sync/task-center.cjs');
(async()=>{
 let rows=[{activity_id:'123',title:'位置签到',endedEvidence:'已结束'}],jobs=[],requests=0;
 const frame={url:()=> 'https://mobilelearn.chaoxing.com/page/active/stuActiveList?courseId=456&classId=789',waitForFunction:async()=>{},evaluate:async()=>rows};
 const context={request:{get:async()=>{requests++;return {status:()=>200,json:async()=>({result:1,data:{title:'位置签到',createtime:1793003188000}}),dispose:async()=>{}}}}};
 const collector=new TaskCenterCollector({context,accepted:new Set(),isCurrent:()=>true,onMessage:async job=>jobs.push(job),onStatus:()=>{}});
 await collector.checkinActivities({frames:()=>[frame]},'测试',{courseId:'456',classId:'789'});
 assert.equal(jobs.length,1);assert.equal(jobs[0].activity_state,'ended');assert.equal(jobs[0].deadline,null);assert.equal(jobs[0].field_evidence.activity_state,'已结束');
 rows=[{activity_id:'123',title:'位置签到',endedEvidence:''}];jobs=[];
 await collector.checkinActivities({frames:()=>[frame]},'测试',{courseId:'456',classId:'789'});
 assert.equal(jobs.length,0,'missing deadline is not treated as active');assert.equal(requests,1);
 collector.checkinCache.get('123').at=Date.now()-31000;
 await collector.checkinActivities({frames:()=>[frame]},'测试',{courseId:'456',classId:'789'});
 assert.equal(requests,2,'detail cache expires after 30 seconds');
 const {chromium}=require('playwright');const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.route('https://mobilelearn.chaoxing.com/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<li activeid="123"><i class="icon-signin-g"></i><div class="right-content"><b class="overHidden2">位置签到</b><span style="display:none">已结束</span></div></li>'}));
  await page.goto(frame.url());jobs=[];
  await collector.checkinActivities({frames:()=>[page.mainFrame()]},'测试',{courseId:'456',classId:'789'});
  assert.equal(jobs.length,0,'hidden status templates cannot mark an activity ended');
  await page.locator('span').evaluate(n=>n.style.display='inline');
  await collector.checkinActivities({frames:()=>[page.mainFrame()]},'测试',{courseId:'456',classId:'789'});
  assert.equal(jobs.length,1);assert.equal(jobs[0].activity_state,'ended');
 }finally{await browser.close()}
 console.log('PASS: explicit ended state without deadline, no fabricated deadline, bounded detail cache');
})().catch(e=>{console.error(e);process.exitCode=1});
