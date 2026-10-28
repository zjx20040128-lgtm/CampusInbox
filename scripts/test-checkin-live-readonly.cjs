'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8765',out=path.resolve(__dirname,'../artifacts/checkin-live-20261027');
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage(),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(['POST','PATCH','DELETE','PUT'].includes(r.method()))writes.push({method:r.method(),path:new URL(r.url()).pathname})});
  const boot=await(await page.request.get(base+'/api/bootstrap')).json();
  const read=async endpoint=>{const r=await page.request.get(base+endpoint,{headers:{Authorization:'Bearer '+boot.token}});assert(r.ok(),endpoint+' '+r.status());return r.json()};
  const state=await read('/api/state'),sync=await read('/api/chaoxing/desktop/status');
  const blocked=state.tasks.filter(t=>['ended','unverified','ambiguous'].includes(t.checkin_verification)&&!['submitted','cancelled'].includes(t.status));
  const checked=[];
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:1000});
   for(const [view,ready] of [['tasks','#taskRows'],['today','.hero'],['inbox','#inboxBody'],['sync','#taskInventorySummary']]){
    await page.goto('about:blank');await page.goto(base+'/#'+view);await page.locator(ready).waitFor();
    if(view==='tasks'){
     await page.locator('#statusFilter').selectOption('active');
     for(const task of blocked)assert.equal(await page.locator(`#taskRows [data-detail="${task.id}"]`).count(),0,'inactive sign-in in active tasks');
     await page.locator('#statusFilter').selectOption('all');
     for(const task of blocked){
      const row=page.locator('.task-row').filter({has:page.locator(`[data-detail="${task.id}"]`)});
      assert.equal(await row.count(),1,'history missing from all tasks');
      assert((await row.innerText()).includes(task.checkin_verification==='ended'?'签到已结束':'签到待核验'));
     }
     if(blocked.length){
      await page.locator(`[data-detail="${blocked[0].id}"]`).click();await page.locator('#detailStatus').waitFor();
      const detail=await page.locator('#taskDetail').innerText();assert(/已停止待办提醒|暂不列入有效待办和提醒/.test(detail));
      await page.locator('#taskDialog').screenshot({path:path.join(out,'ended-detail-'+width+'.png')});await page.locator('#taskDialog [data-close]').click();
     }
    }
    if(view==='today')for(const task of blocked)assert.equal(await page.locator(`.priority-item [data-detail="${task.id}"]`).count(),0);
    if(view==='inbox'){
     for(const p of state.proposals.filter(p=>p.checkin_unverified||p.checkin_ambiguous||p.checkin_expired)){
      const button=page.locator(`[data-confirm="${p.id}"]:not([data-conflict-resolution])`);
      if(await button.count())assert(await button.isDisabled(),'blocked sign-in confirm enabled');
     }
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),view+' overflow');
    await page.screenshot({path:path.join(out,view+'-'+width+'.png'),fullPage:true});checked.push(view+'-'+width);
   }
  }
  const after=await read('/api/state');
  const result={checked,errors,writes,task_count:state.tasks.length,proposal_count:state.proposals.length,
   checkins:state.tasks.filter(t=>t.checkin_verification).map(t=>({id:t.id,title:t.title,deadline:t.deadline,status:t.status,verification:t.checkin_verification})),
   guarded_proposals:state.proposals.filter(p=>p.checkin_unverified||p.checkin_ambiguous||p.checkin_expired).map(p=>({id:p.id,title:p.candidate.title,unverified:!!p.checkin_unverified,ambiguous:!!p.checkin_ambiguous,ended:!!p.checkin_expired})),
   sync:{enabled:sync.enabled,state:sync.state,stage:sync.stage,reason:sync.reason,sources:Object.fromEntries(Object.entries(sync.sources||{}).map(([k,v])=>[k,{state:v.state,last_checked:v.last_checked,last_success:v.last_success,pending_count:v.pending_count,reason:v.reason}]))},
   before_after_counts:{before:[state.tasks.length,state.proposals.length,state.message_total],after:[after.tasks.length,after.proposals.length,after.message_total]}};
  fs.writeFileSync(path.join(out,'readonly-result.json'),JSON.stringify(result,null,2));
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
