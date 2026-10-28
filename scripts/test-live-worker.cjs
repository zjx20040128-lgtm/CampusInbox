'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),os=require('os'),{spawn}=require('child_process');
const root=path.resolve(__dirname,'..'),directory=fs.mkdtempSync(path.join(os.tmpdir(),'campusinbox-live-worker-'));
const preload=path.join(directory,'fixture.cjs'),clock=path.join(directory,'inserted.json');let worker;
fs.writeFileSync(preload,`
const fs=require('fs'),{chromium}=require('playwright'),launch=chromium.launch.bind(chromium);
chromium.launch=async options=>{
 const b=await launch(options),newContext=b.newContext.bind(b);
 b.newContext=async options=>{
  const c=await newContext(options);await c.exposeBinding('fixtureInserted',()=>fs.writeFileSync(${JSON.stringify(clock)},JSON.stringify(Date.now())));
  await c.route('**/*',async route=>{
   if(route.request().method()!=='GET')throw Error('No platform writes allowed');
   const u=new URL(route.request().url());let body='';
   if(u.hostname==='i.chaoxing.com')body='<iframe src="https://notice.chaoxing.com/pc/notice/myNotice"></iframe><iframe src="https://mooc2-ans.chaoxing.com/visit/interaction"></iframe>';
   else if(u.hostname==='notice.chaoxing.com')body='<div class="dataBody" style="min-height:20px"></div><div class="loadMore loadEnd">已经加载完</div>';
   else if(u.hostname==='mooc2-ans.chaoxing.com')body='<div class="null-data">暂无课程</div>';
   else if(u.hostname==='fe.chaoxing.com')body=${JSON.stringify("<div class=\"conversation-list\"><div class=\"conversation-item is-selected\" data-conversation-id=\"live-course\"><span class=\"name\">课程甲</span><span class=\"preview\">原消息</span></div></div><div class=\"chat-header\"><span class=\"chat-name\">课程甲</span></div><div class=\"message-area\"><div class=\"message-row is-other\" data-msg-id=\"live-old\"><span class=\"sender-name\">老师</span><span class=\"message-time\">2026-10-25 12:00</span><div class=\"bubble-text\">原消息</div></div></div><script>setTimeout(async()=>{await fixtureInserted();document.querySelector('.preview').textContent='实时到达';const n=document.createElement('div');n.className='message-row is-other';n.dataset.msgId='live-new';n.innerHTML='<span class=\"sender-name\">老师</span><span class=\"message-time\">2026-10-25 12:01</span><div class=\"bubble-text\">实时到达</div>';const stamp=document.createElement('div');stamp.className='time-stamp';stamp.textContent='2026-10-25 12:01';document.querySelector('.message-area').append(stamp,n);},3000);</script>")};
   await route.fulfill({contentType:'text/html; charset=utf-8',body});
  });return c;
 };return b;
};`);
(async()=>{
 const env={...process.env,NODE_OPTIONS:'--require '+JSON.stringify(preload)};
 worker=spawn(process.execPath,[path.join(root,'desktop-sync/worker.cjs'),directory],{cwd:root,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
 let buffer='',received=[],settle;const delivered=new Promise(resolve=>settle=resolve);const diagnostics=[];
 worker.stdout.on('data',chunk=>{buffer+=chunk.toString();let end;while((end=buffer.indexOf('\n'))>=0){let value;try{value=JSON.parse(buffer.slice(0,end))}catch{}buffer=buffer.slice(end+1);if(value)diagnostics.push(value);if(value?.type==='chat'){
  worker.stdin.write(JSON.stringify({type:'accepted',id:value.job.message_id,complete:true})+'\n');
  if(value.job.message_id==='live-new'){received.push({at:Date.now(),job:value.job});settle();}
 }}});worker.stderr.on('data',chunk=>diagnostics.push({stderr:chunk.toString().slice(0,800)}));
 worker.stdin.write(JSON.stringify({type:'start',session:{cookies:[],origins:[]},accepted:[]})+'\n');
 let timeout;try{await Promise.race([delivered,new Promise((_,reject)=>timeout=setTimeout(()=>reject(Error('DOM change was not collected before fallback: '+JSON.stringify(diagnostics.slice(-8)))),20000))])}finally{clearTimeout(timeout)}
 const delay=received[0].at-JSON.parse(fs.readFileSync(clock,'utf8'));
 assert.ok(delay<3000,'DOM-triggered capture took '+delay+' ms');assert.equal(received[0].job.text,'实时到达');
 assert.equal(received[0].job.captured_at,'2026-10-25T12:01:00+08:00','publication time stays the source timestamp');
 await new Promise(resolve=>setTimeout(resolve,1800));assert.equal(received.length,1,'accepted source cannot replay from observer-driven scans');
 console.log('PASS real worker DOM -> chat collection in '+delay+' ms, before fallback; original publication, dedup and read-only platform requests');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{
 if(worker&&worker.exitCode===null){worker.stdin.write('{"type":"close"}\n');await new Promise(resolve=>setTimeout(resolve,700));worker.kill();}
 assert.equal(path.dirname(directory),os.tmpdir());assert.ok(path.basename(directory).startsWith('campusinbox-live-worker-'));fs.rmSync(directory,{recursive:true,force:true,maxRetries:3,retryDelay:100});
});
