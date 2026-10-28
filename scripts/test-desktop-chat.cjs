/* Real browser + sanitized official DOM fixtures; no account data. */
'use strict';
const assert=require('node:assert/strict');const {chromium}=require('playwright');
const {ChatCollector}=require('../desktop-sync/chat.cjs');
let browser;
(async()=>{
 browser=await chromium.launch({channel:'msedge',headless:true});const context=await browser.newContext();
 let round=0,broken=false,live=true,mode='normal';const messages=[],states=[],accepted=new Set();
 await context.route('https://fe.chaoxing.com/**',async route=>{
  if(broken)return route.abort('connectionfailed');round++;
  if(mode==='empty-list')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div class="main-layout"><div class="conversation-list"><p>暂无会话</p></div></div>'});
  if(mode==='empty-chat')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div class="main-layout"><div class="conversation-list"><div class="conversation-item is-selected"><span class="name">空会话</span></div></div><div class="chat-header"><span class="chat-name">空会话</span></div><div class="message-area"><p>暂无消息</p></div></div>'});
  if(mode==='media-chat')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div class="conversation-list"><div class="conversation-item is-selected"><span class="name">图片会话</span></div></div><div class="chat-header"><span class="chat-name">图片会话</span></div><div class="message-area"><div class="message-row is-other" data-msg-id="chat-image"><div class="bubble-text">请查看图中要求</div><img alt="要求图片" src="data:image/gif;base64,R0lGODlhAQABAAAAACw="></div></div>'});
  if(mode==='blank-chat')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div class="conversation-list"><div class="conversation-item is-selected"><span class="name">未加载会话</span></div></div><div class="chat-header"><span class="chat-name">未加载会话</span></div><div class="message-area"></div>'});
  if(mode==='delayed-chat')return route.fulfill({contentType:'text/html; charset=utf-8',body:`<div class="conversation-list"><div class="conversation-item is-selected"><span class="name">慢会话</span></div></div><div class="chat-header"><span class="chat-name">慢会话</span></div><div class="message-area"></div><script>setTimeout(()=>{document.querySelector(".message-area").innerHTML='<div class="time-stamp">10-08 20:24</div><div class="message-row is-other" data-msg-id="chat-slow"><div class="bubble-text">慢加载消息</div></div>';window.fixturePushApplied=true},1500)</script>`});
  const late=round>1?'<div class="message-row is-other" data-msg-id="chat-new"><span class="sender-name">甲老师</span><div class="bubble-text">。</div></div>':'';
  const one='<div class="time-stamp">10-08 20:24</div><div class="message-row is-other" data-msg-id="chat-one"><span class="sender-name">甲老师</span><div class="bubble-text">1</div></div>'+late;
  const two='<div class="time-stamp">10-08 20:58</div><div class="message-row is-other" data-msg-id="chat-two"><span class="sender-name">乙老师</span><div class="bubble-text">请在明天提交读书报告。</div></div>';
  const body=`<div class="conversation-list"><div class="conversation-item is-selected"><span class="name">甲老师的备注</span></div><div class="conversation-item"><span class="name">乙老师</span></div></div><div class="chat-header"><span class="chat-name">甲老师</span></div><div class="message-area">${one}</div><script>const bodies=[${JSON.stringify(one)},${JSON.stringify(two)}];setTimeout(()=>{bodies[0]+=${JSON.stringify('<div class="message-row is-other" data-msg-id="chat-new"><span class="sender-name">甲老师</span><div class="bubble-text">。</div></div>')};window.fixturePushApplied=true},1500);document.querySelectorAll('.conversation-item').forEach((e,i)=>e.onclick=()=>{document.querySelectorAll('.conversation-item').forEach(n=>n.classList.remove('is-selected'));e.classList.add('is-selected');setTimeout(()=>document.querySelector('.chat-name').textContent=i===0?'甲老师':'乙老师',600);setTimeout(()=>document.querySelector('.message-area').innerHTML=bodies[i],300)});</script>`;
  await route.fulfill({contentType:'text/html; charset=utf-8',body});
 });
 const collector=new ChatCollector({context,accepted,isCurrent:()=>live,onMessage:job=>{messages.push(job);accepted.add(job.message_id)},onStatus:state=>states.push(state)});
 await collector.sweep();assert.deepEqual(messages.map(m=>[m.message_id,m.text,m.conversation]),[['chat-one','1','甲老师'],['chat-two','请在明天提交读书报告。','乙老师']]);
 assert.equal(messages[1].captured_at,'2026-10-08T20:58:00+08:00');assert.equal(states.at(-1).state,'connected');assert.equal(states.at(-1).stage,'','a successful chat check must not show a retry stage');
 await context.pages()[0].waitForFunction(()=>window.fixturePushApplied===true);await collector.sweep();assert.equal(messages.length,3);assert.equal(messages.at(-1).message_id,'chat-new');assert.equal(messages.at(-1).text,'。');
 broken=true;await collector.close();await collector.sweep();assert.equal(states.at(-1).state,'retrying');assert.equal(messages.length,3);
 broken=false;await collector.sweep();assert.equal(messages.length,3);assert.equal(states.at(-1).state,'connected');
 await collector.close();mode='empty-list';await collector.sweep();assert.equal(states.at(-1).state,'connected');assert.equal(messages.length,3);
 await collector.close();mode='empty-chat';await collector.sweep();assert.equal(states.at(-1).state,'connected');assert.equal(messages.length,3);
 await collector.close();mode='blank-chat';await collector.sweep();assert.equal(states.at(-1).state,'partial','an unresolved blank conversation must finish the sweep instead of staying syncing forever');assert.equal(states.at(-1).checked,true);assert.equal(states.at(-1).error,'chat');
 await collector.close();mode='delayed-chat';await collector.sweep();assert.equal(states.at(-1).state,'connected','a slow conversation is read once its messages arrive');const before=round;await collector.sweep();assert.equal(round,before,'a slow message page must not be reloaded between sweeps');assert.equal(messages.at(-1).message_id,'chat-slow');assert.equal(states.at(-1).state,'connected');
 await collector.close();mode='media-chat';await collector.sweep();assert.equal(messages.at(-1).message_id,'chat-image');assert.equal(states.at(-1).state,'partial');assert.equal(states.at(-1).media_pending_count,1,'saved chat text must not hide an unread image');
 assert.equal(states.at(-1).reason,'','media-only gaps are not DOM parsing failures');assert.equal(states.at(-1).error,'coverage');
 live=false;await collector.sweep();assert.equal(messages.length,5);await collector.close();
 console.log('PASS: multiple chat conversations, short text, delayed conversation switch, new messages, stable replay, network recovery and pause');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close()});
