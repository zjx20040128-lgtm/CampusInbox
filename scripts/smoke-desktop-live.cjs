/* Read-only live UI acceptance. No task actions, platform writes, or message text in output. */
'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),{chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/#sync');
  await page.waitForFunction(()=>{const text=document.querySelector('#desktopSources')?.textContent||'';return text.includes('聊天：已同步')&&text.includes('课程通知：已同步')},null,{timeout:45000});
  assert(!/待重试|本轮未读/.test(await page.locator('#desktopSources').textContent()),'successful sources must not show retry hints');
  const snapshot=await page.evaluate(async()=>{
   const token=(await (await fetch('/api/bootstrap')).json()).token,headers={Authorization:'Bearer '+token};
   const state=await (await fetch('/api/state',{headers})).json(),sync=await (await fetch('/api/chaoxing/desktop/status',{headers})).json();
   const empty=state.messages.filter(m=>m.external?.notice_body_state==='empty');
   return {sync,task_count:state.tasks.length,message_count:state.messages.length,empty_count:empty.length,empty_id:empty[0]?.id};
  });
  assert(snapshot.empty_id,'live account should contain the retained title-only notices');
  await page.goto('http://127.0.0.1:8765/#inbox');
  await page.locator('[data-inbox-tab="messages"]').click();
  await page.locator('[data-message-detail="'+snapshot.empty_id+'"]').click();
  await page.locator('#messageDetail').getByText('原通知正文为空，已保存标题、来源与发布时间。',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);delete snapshot.empty_id;
  const result={passed:true,checked_at:new Date().toISOString(),scope:'real account; read-only local UI; currently rendered notices and chats',...snapshot,empty_body_hint:true,console_errors:errors};
  fs.writeFileSync(path.join(__dirname,'../docs/verification/desktop-live-smoke-result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
