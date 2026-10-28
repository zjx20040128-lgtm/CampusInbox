/* Read-only smoke check; account session is supplied through stdin. */
'use strict';
const {chromium}=require('playwright');
const {TaskCenterCollector}=require('../desktop-sync/task-center.cjs');
async function run(session){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({storageState:session});let found=0;
  const collector=new TaskCenterCollector({context,accepted:new Set(),cursor:0,isCurrent:()=>true,onMessage:job=>{found++;console.log(JSON.stringify({kind:job.task_type,deadline_known:Boolean(job.deadline),submission_known:Boolean(job.submission_method)}))},onStatus:status=>console.log(JSON.stringify({state:status.state,checked:status.checked_count,captured:status.captured_count,failed:status.failed_count,pending:status.pending_count,course_count:status.course_count,stage:status.stage,reason:status.reason}))});
  for(let i=0;i<3;i++)await collector.sweep();
  await collector.close();console.log(JSON.stringify({found}));
 }finally{await browser.close()}
}
let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>raw+=x);process.stdin.on('end',()=>{try{const session=JSON.parse(raw);raw='';run(session).catch(e=>{console.error(e.name+': '+String(e.message).slice(0,200));process.exitCode=1})}catch{process.exitCode=1}});
