const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const parser = require('../browser-companion/parser.js');
const now = new Date('2026-10-06T02:00:00Z');

test('loaded title-only notices are retained but unresolved empty pages are not',()=>{
  const notices=require('../browser-companion/notices.js');
  const fields={url:'https://notice.chaoxing.com/pc/notice/$CACG$empty/detail',title:'普通通知',text:'',attachments:[],time:'10-06 09:00'};
  assert.equal(notices.noticeFromFields(fields),null);
  const job=notices.noticeFromFields({...fields,empty_body_ready:true});
  assert(job);assert.equal(job.text,'');assert.equal(job.title,fields.title);
});

test('web display times use Beijing date including yesterday and year rollover', () => {
  assert.equal(parser.parseTime('昨天 23:57', now), '2026-10-05T23:57:00+08:00');
  assert.equal(parser.parseTime('10-04 23:29', now), '2026-10-04T23:29:00+08:00');
  assert.equal(parser.parseTime('09:30', now), '2026-10-06T09:30:00+08:00');
  assert.equal(parser.parseTime('12-31 23:59', new Date('2027-01-01T02:00:00Z')), '2026-12-31T23:59:00+08:00');
  for (const label of ['刚刚', '', '02-30 12:00', '今天 25:10', '10-20 12:00']) assert.equal(parser.parseTime(label, now), null);
});

test('chat rows retain original body and timestamp groups, skip attachments and missing identity', () => {
  const rows = [
    {time: '昨天 23:22'}, {id: 'm1', text: '原文\n第二行', sender: '同学', direction: 'received'},
    {id: 'image1', text: ''}, {text: '没有编号'}, {time: '昨天 23:57'},
    {id: 'm2', text: '原文\n第二行', sender: '我', direction: 'sent'}, {id: 'm2', text: 'duplicate'}
  ];
  const messages = parser.messagesFromRows(rows, '测试会话', now);
  assert.equal(messages.length, 2);
  assert.equal(messages[0].text, rows[1].text);
  assert.equal(messages[0].captured_at, '2026-10-05T23:22:00+08:00');
  assert.equal(messages[1].captured_at, '2026-10-05T23:57:00+08:00');
  assert.equal(messages[1].direction, 'sent');
  assert.equal(parser.messagesFromRows([{id:'m3',text:'明天截止'}], '未知时间', now)[0].captured_at, null);
});

async function worker(fetchStatus = 201, onFetch = () => {}) {
  const data = {enabled:true, token:'scoped-test', queue:[], delivered:0};
  let listener;
  const callbacks = {addListener(){}};
  const chrome = {
    runtime:{id:'test-extension', onMessage:{addListener(fn){listener=fn}},onStartup:callbacks,onInstalled:callbacks},
    storage:{local:{async get(){return structuredClone(data)},async set(v){Object.assign(data,structuredClone(v))},async setAccessLevel(){}},onChanged:callbacks},
    alarms:{async create(){},onAlarm:callbacks}
  };
  const calls=[];
  const context = {chrome, URL, AbortSignal, AbortController, setTimeout, clearTimeout, structuredClone, console, Date, Uint8Array, btoa,
    fetch:async (url, init)=>{assert.equal(url,'http://127.0.0.1:8765/api/chaoxing/messages');assert.equal(init.headers.Authorization,'Bearer scoped-test');calls.push(init);await onFetch(data,calls);const status=typeof fetchStatus==='function'?fetchStatus(calls.length):fetchStatus;return {status,ok:status<300}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../browser-companion/background.js'),'utf8'),context);
  const send = (message,url='https://fe.chaoxing.com/front/webim/index.html') => new Promise(resolve => listener(message,{id:'test-extension',url},resolve));
  return {data,send,calls};
}
const message = {message_id:'m1',text:'真实文字',conversation:'测试会话',sender:'同学',display_time:'昨天 23:22',captured_at:'2026-10-05T23:22:00+08:00',direction:'received'};

test('queue persists offline messages and only removes confirmed delivery',async()=>{
  const failed=await worker(500);
  await failed.send({type:'capture',messages:[message,message]});
  assert.equal(failed.data.queue.length,1);
  assert.equal(failed.data.delivered,0);
  assert.match(failed.data.lastError,/500/);
  for (const status of [200,201]) {
    const success=await worker(status);
    await success.send({type:'capture',messages:[message]});
    assert.equal(success.data.queue.length,0);
    assert.equal(success.data.delivered,1);
  }
});

test('disabled capture and non platform senders cannot enqueue messages',async()=>{
  const w=await worker();
  await w.send({type:'capture',messages:[message]},'https://evil.example');
  assert.equal(w.data.delivered,0);
  w.data.enabled=false;
  await w.send({type:'capture',messages:[message]});
  assert.equal(w.data.queue.length,0);
  assert.equal(w.data.delivered,0);
});

test('switching off during delivery leaves remaining messages queued',async()=>{
  const w=await worker(201, async data=>{data.enabled=false});
  await w.send({type:'capture',messages:[message,{...message,message_id:'m2'}]});
  assert.equal(w.calls.length,1);
  assert.equal(w.data.queue.length,1);
  assert.equal(w.data.queue[0].message_id,'m2');
});

test('course notice timestamps preserve weekdays and publication dates',()=>{
  assert.equal(parser.parseTime('10-08(星期四) 12:06',new Date('2026-10-08T06:00:00Z')),'2026-10-08T12:06:00+08:00');
  assert.equal(parser.parseTime('2025-04-29（星期二）20:04',now),'2025-04-29T20:04:00+08:00');
});
test('course notification jobs keep native identity, original body and listed attachments',()=>{
  let notices;try{notices=require('../browser-companion/notices.js')}catch{assert.fail('course notification parser is missing')}
  const job=notices.noticeFromFields({id:'fixture-1',url:'https://notice.chaoxing.com/pc/notice/$CACG$fixture-1/detail',title:'《示例课程》第二次课课前阅读',text:'请阅读材料。\n请在明天上课前完成。',sender:'示例老师',time:'10-08(星期四) 12:06',attachments:[{name:'课前阅读说明.docx',url:'https://d0.cldisk.com/download/'+'a'.repeat(32),size:3000}]},new Date('2026-10-08T06:00:00Z'));
  assert.equal(job.kind,'course_notice');assert.equal(job.message_id,'notice_fixture-1');assert.equal(job.course,'示例课程');assert.equal(job.captured_at,'2026-10-08T12:06:00+08:00');assert.equal(job.text,'请阅读材料。\n请在明天上课前完成。');assert.equal(job.attachments[0].name,'课前阅读说明.docx');
  assert.equal(notices.noticeFromFields({id:'fixture-1',url:job.url,title:'登录',text:''},now),null);
  assert.equal(notices.safeDetailURL('https://evil.example/detail','https://notice.chaoxing.com/pc/notice/myNotice'),null);
});
test('notice capture is permitted only from the official notification paths',async()=>{
  const w=await worker();const notice={...message,kind:'course_notice',message_id:'notice_m1',title:'《示例课程》课前阅读',course:'示例课程',url:'https://notice.chaoxing.com/pc/notice/$CACG$fixture-1/detail',attachments:[]};
  await w.send({type:'capture',messages:[notice]},'https://notice.chaoxing.com/pc/notice/myNotice');assert.equal(w.data.delivered,1);
  for(const url of ['https://notice.chaoxing.com/evil','https://notice.chaoxing.com.evil.example/pc/notice/myNotice','https://i.chaoxing.com/base'])await w.send({type:'capture',messages:[{...notice,message_id:url}]},url);
  assert.equal(w.data.delivered,1);
});
test('disabled notice scan exposes disabled state without collecting details',async()=>{
  const w=await worker();w.data.enabled=false;
  const state=await w.send({type:'sync-state'},'https://notice.chaoxing.com/pc/notice/myNotice');assert.equal(state.enabled,false);
  await w.send({type:'capture',messages:[{...message,kind:'course_notice'}]},'https://notice.chaoxing.com/pc/notice/myNotice');assert.equal(w.calls.length,0);
});

test('a permanent bad payload is retained separately and does not block later notices',async()=>{
  const w=await worker(count=>count===1?400:201);
  await w.send({type:'capture',messages:[message,{...message,message_id:'m2'}]});
  assert.equal(w.calls.length,2);assert.equal(w.data.queue.length,0);assert.equal(w.data.rejected.length,1);assert.equal(w.data.rejected[0].text,message.text);assert.equal(w.data.delivered,1);
  await w.send({type:'capture',messages:[message]});assert.equal(w.calls.length,2);assert.equal(w.data.rejected.length,1);
});

test('disabling during attachment download prevents extraction and preserves queued evidence',async()=>{
  let listener;const data={enabled:true,token:'scoped-test',queue:[]};const callbacks={addListener(){}};const calls=[];
  const chrome={runtime:{id:'test-extension',onMessage:{addListener(fn){listener=fn}},onStartup:callbacks,onInstalled:callbacks},storage:{local:{async get(){return structuredClone(data)},async set(v){Object.assign(data,structuredClone(v))},async setAccessLevel(){}},onChanged:callbacks},alarms:{async create(){},onAlarm:callbacks}};
  const fetch=async(url)=>{calls.push(url);data.enabled=false;const response=new Response('file');Object.defineProperty(response,'url',{value:url});return response};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../browser-companion/background.js'),'utf8'),{chrome,fetch,URL,AbortSignal,AbortController,setTimeout,clearTimeout,structuredClone,Date,Uint8Array,btoa});
  const notice={...message,kind:'course_notice',title:'课前阅读',message_id:'notice_test',attachments:[{name:'阅读说明.docx',url:'https://d0.cldisk.com/download/'+'a'.repeat(32),size:4}]};
  await new Promise(resolve=>listener({type:'capture',messages:[notice]},{id:'test-extension',url:'https://notice.chaoxing.com/pc/notice/myNotice'},resolve));
  assert.equal(calls.length,1);assert.equal(data.queue.length,1);assert.equal(data.queue[0].text,message.text);
});
