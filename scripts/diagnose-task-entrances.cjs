/* Read-only course entrance diagnostics; encrypted session is supplied through stdin. */
'use strict';
const {chromium}=require('playwright'),{TaskCenterCollector}=require('../desktop-sync/task-center.cjs');
async function run(session){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({storageState:session});
  const collector=new TaskCenterCollector({context,accepted:new Set(),isCurrent:()=>true,onMessage:()=>{},onStatus:()=>{}});
  const frame=await collector.portal();
  for(const index of [0,3]){
   if(index>=await frame.locator('a.color1').count())continue;
   const before=context.pages();await frame.locator('a.color1').nth(index).click({timeout:8000});
   let tab;
   for(let i=0;i<30&&!tab;i++){tab=context.pages().find(p=>!before.includes(p)&&p.url().startsWith('https://'));if(!tab)await new Promise(r=>setTimeout(r,250))}
   if(!tab){console.log(JSON.stringify({course_index:index+1,popup:false}));continue;}
   await tab.waitForLoadState('domcontentloaded').catch(()=>{});
   await tab.locator('li').filter({hasText:'作业'}).first().waitFor({timeout:10000}).catch(()=>{});
   const info=await tab.evaluate(()=>({path:location.pathname,work_li:[...document.querySelectorAll('li')].filter(n=>n.textContent.includes('作业')).length,work_a:[...document.querySelectorAll('a')].filter(n=>n.textContent.includes('作业')).length,exam_li:[...document.querySelectorAll('li')].filter(n=>n.textContent.includes('考试')).length,blocked:/无权访问|没有权限|课程不存在|课程已结束/.test(document.body.innerText)}));
   console.log(JSON.stringify({course_index:index+1,...info}));await tab.close();
  }
  await collector.close();
 }finally{await browser.close()}
}
let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',part=>raw+=part);process.stdin.on('end',()=>{let session;try{session=JSON.parse(raw);raw=''}catch{process.exitCode=1;return}run(session).catch(e=>{console.error(e.name);process.exitCode=1})});
