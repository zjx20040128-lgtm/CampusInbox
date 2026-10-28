'use strict';
const assert=require('node:assert/strict'),{chromium}=require('playwright');
const {installLiveCapture}=require('../desktop-sync/live-capture.cjs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext(),events=[];
  await installLiveCapture(context,event=>events.push(event));
  await context.route('**/*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:new URL(route.request().url()).hostname==='notice.chaoxing.com'?'<div class="dataBody">暂无通知</div>':'<div class="conversation-list"><div class="conversation-item" data-conversation-id="c1"><span class="name">甲老师</span><span class="preview">旧消息</span></div></div><div class="message-area"><div class="message-row" data-msg-id="m1">旧正文</div></div>'}));
  const page=await context.newPage();await page.goto('https://fe.chaoxing.com/front/webim/index.html');await page.waitForTimeout(1000);events.length=0;
  await page.locator('.conversation-item').evaluate(n=>n.classList.add('is-selected'));await page.waitForTimeout(1000);assert.equal(events.length,0,'selection styling cannot schedule another scan');
  const start=Date.now();await page.evaluate(()=>{
   document.querySelector('.preview').textContent='新消息';
   const n=document.createElement('div');n.className='message-row';n.dataset.msgId='m2';n.textContent='新消息';document.querySelector('.message-area').append(n);
  });
  await assert.doesNotReject(async()=>{await page.waitForTimeout(1300);assert.equal(events.length,1)});
  assert.ok(Date.now()-start<3000);assert.equal(events[0].kind,'chat');assert.ok(events[0].conversations.includes('c1'));
  events.length=0;await page.locator('.message-area').evaluate(n=>{const saved=n.innerHTML;n.innerHTML='';n.innerHTML=saved});await page.waitForTimeout(1200);assert.equal(events.length,0,'rerendering known messages cannot loop');
  await page.goto('https://notice.chaoxing.com/pc/notice/myNotice');await page.waitForTimeout(1000);events.length=0;
  await page.evaluate(()=>{const n=document.createElement('div');n.className='dataBody_item';n.dataset.id='notice-1';n.textContent='新通知';document.body.append(n)});await page.waitForTimeout(1200);assert.equal(events[0].kind,'notice');
  await page.goto('https://untrusted.example/');await page.waitForTimeout(1000);events.length=0;await page.evaluate(()=>{document.querySelector('.preview').textContent='伪造通知'});await page.waitForTimeout(1200);assert.equal(events.length,0);
  await context.close();console.log('PASS official DOM changes, debounce, chat priority IDs, rerender/selection dedup, new notices and untrusted-origin rejection');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
