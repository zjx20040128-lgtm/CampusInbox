/* Isolated fixture acceptance. No platform account or production data is used. */
'use strict';
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const {spawn,execFileSync}=require('child_process');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),recovery=process.argv.includes('--recovery'),chat=process.argv.includes('--chat');
const python=process.env.CI_PYTHON||path.join(root,'.venv','Scripts','python.exe');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'desktop-sync-test-'));let server,browser,url,main;
const docx=path.join(temporary,'instructions.docx'),preload=path.join(temporary,'fixture.cjs');
const chatPush=chat?'setTimeout(()=>{bodies[0]+='+JSON.stringify('<div class="message-row is-other" data-msg-id="fixture-chat-new"><span class="sender-name">甲老师</span><div class="bubble-text">。</div></div>')+';if(document.querySelector(".conversation-item.is-selected .name")?.textContent==="甲老师")document.querySelector(".message-area").innerHTML=bodies[0]},5000);':'';
execFileSync(python,['-c',"import sys,zipfile; z=zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED); z.write(sys.argv[2],'word/document.xml'); z.close()",docx,path.join(root,'samples/chaoxing-reading-instructions.xml')],{windowsHide:true});
fs.writeFileSync(preload,`
const fs=require('fs'),{chromium}=require('playwright');const launch=chromium.launch.bind(chromium);
const timer=global.setTimeout;global.setTimeout=(fn,ms,...args)=>timer(fn,ms===60000?3000:ms===10000?5000:ms,...args);
const originalFetch=global.fetch;global.fetch=(target,options)=>String(target).startsWith('https://d0.cldisk.com/download/')?Promise.resolve(new Response(fs.readFileSync(${JSON.stringify(docx)}))):originalFetch(target,options);
chromium.launch=async options=>{
 const browser=await launch(options),newContext=browser.newContext.bind(browser);
 browser.newContext=async options=>{
  const context=await newContext(options);let lists=0,detailFailures=0,chatVisits=0;
  await context.route('**/*',async route=>{
   const u=new URL(route.request().url());if(!u.hostname.endsWith('.chaoxing.com'))return route.abort();
   let body='<!doctype html><html><body></body></html>';
   if(u.hostname==='i.chaoxing.com'){
    const signed=(await context.cookies('https://i.chaoxing.com')).some(c=>c.name==='fixture_auth'&&c.value==='yes');
    if(signed)body='<a href="https://notice.chaoxing.com/pc/notice/myNotice" onclick="this.nextElementSibling.src=this.href;return false">收件箱</a><iframe></iframe><iframe src="https://mooc2-ans.chaoxing.com/visit/interaction"></iframe>';
    else{
     const svg='<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><rect width="180" height="180" fill="white"/><path d="M10 10H65V65H10ZM115 10H170V65H115ZM10 115H65V170H10ZM90 85H165V100H90ZM80 120H160V135H80Z" fill="#215a47"/><text x="75" y="160" font-size="12">扫码演示</text></svg>';
     body='<h1>隔离扫码流程演示</h1><img id="quickCode" src="data:image/svg+xml;base64,'+Buffer.from(svg).toString('base64')+'"><script>setTimeout(()=>{document.cookie="fixture_auth=yes;Max-Age=3600;Secure;Path=/";location.href="https://i.chaoxing.com/base"},7000)</script>';
     if(${recovery})body='<iframe src="https://passport2.chaoxing.com/login"></iframe>';
    }
   }else if(u.hostname==='passport2.chaoxing.com'){
    const svg='<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><rect width="180" height="180" fill="white"/><text x="20" y="90">官方子页面扫码演示</text></svg>';
    body='<img id="quickCode" src="data:image/svg+xml;base64,'+Buffer.from(svg).toString('base64')+'"><script>setTimeout(()=>{document.cookie="fixture_auth=yes;Max-Age=3600;Secure;Domain=.chaoxing.com;Path=/";top.location.href="https://i.chaoxing.com/base"},7000)</script>';
   }else if(u.hostname==='mooc2-ans.chaoxing.com'){
    if(u.pathname==='/visit/interaction')body='<a class="color1" target="_blank" href="https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu?courseId=1&clazzid=2">示例课程</a>';
    else body='<ul><li onclick="document.querySelector(&quot;iframe&quot;).src=&quot;https://mooc1.chaoxing.com/mooc2/work/list&quot;">作业</li><li onclick="document.querySelector(&quot;iframe&quot;).src=&quot;https://mooc1.chaoxing.com/exam-ans/mooc2/exam/exam-list&quot;">考试</li></ul><iframe></iframe>';
   }else if(u.hostname==='mooc1.chaoxing.com'){
    body='<div class="null-data">暂无任务</div>';
   }else if(u.hostname==='fe.chaoxing.com'){
    chatVisits++;
    const first=${chat}?'<div class="time-stamp">10-08 20:24</div><div class="message-row is-other" data-msg-id="fixture-chat-one"><span class="sender-name">甲老师</span><div class="bubble-text">1</div></div>'+ (chatVisits>=2?'<div class="message-row is-other" data-msg-id="fixture-chat-new"><span class="sender-name">甲老师</span><div class="bubble-text">。</div></div>':''):'<div class="message-row" data-msg-id="fixture-media-only"><div class="bubble"></div></div>';
    const second='<div class="time-stamp">10-08 20:58</div><div class="message-row is-other" data-msg-id="fixture-chat-two"><span class="sender-name">乙老师</span><div class="bubble-text">。</div></div>';
    body='<div class="conversation-list"><div class="conversation-item is-selected"><span class="name">甲老师</span></div>'+(${chat}?'<div class="conversation-item"><span class="name">乙老师</span></div>':'')+'</div><div class="chat-header"><span class="chat-name">甲老师</span></div><div class="message-area">'+first+'</div><script>const bodies=['+JSON.stringify(first)+','+JSON.stringify(second)+'];'+${JSON.stringify(chatPush)}+'document.querySelectorAll(".conversation-item").forEach((e,i)=>e.onclick=()=>{document.querySelectorAll(".conversation-item").forEach(n=>n.classList.remove("is-selected"));e.classList.add("is-selected");document.querySelector(".chat-name").textContent=e.querySelector(".name").textContent;setTimeout(()=>document.querySelector(".message-area").innerHTML=bodies[i],100)});</script>';
   }else if(u.hostname==='notice.chaoxing.com'){
    const detail=u.pathname.endsWith('/detail');if(${recovery}&&!detail&&lists>=1&&lists<=3){lists++;return route.abort('connectionfailed')}if(${recovery}&&detail&&detailFailures++===0)return route.abort('connectionfailed');body=fs.readFileSync(${JSON.stringify(path.join(root,'samples'))}+'/'+(detail?'chaoxing-notice-detail.html':'chaoxing-notice-list.html'),'utf8');
    if(!detail)body=body.replace('</body>','<div class="loadMore loadEnd">已经加载完</div></body>');
    if(!detail&&++lists>=(${recovery}?7:3))body=body.replace('</ul>','<li class="dataBody_item" data-id="fixture-row-2"><div class="openNotice" data-sendtag="0" data-url="/pc/notice/$CACG$fixture-2/detail"><a class="notice_title">《示例课程》课前阅读</a><span class="notice_time">10-08 12:06</span></div></li></ul>');
   }
   await route.fulfill({contentType:'text/html; charset=utf-8',body});
  });return context;
 };return browser;
};
`);
async function start(){
 // This journey observes the sanitized 10/8 notice while its 10/9 task is active.
 const bootstrap="import subprocess,sys,runpy\nfrom unittest.mock import patch\noriginal=subprocess.Popen\nworkerlog=sys.argv[1]\ndef launch(*args,**kwargs):\n if str(args[0][0]).endswith('node.exe'): kwargs['stderr']=open(workerlog,'ab')\n return original(*args,**kwargs)\nsubprocess.Popen=launch\nsys.argv=sys.argv[2:]\nwith patch('courseinbox.core.now_iso',return_value='2026-10-08T12:06:00+08:00'):\n runpy.run_path(sys.argv[0],run_name='__main__')";
 server=spawn(python,['-c',bootstrap,path.join(temporary,'fixture-errors.log'),path.join(root,'server.py'),'--port','0','--data-dir',temporary],{cwd:root,windowsHide:true,env:{...process.env,NODE_OPTIONS:'--require="'+preload.replaceAll('\\','/')+'"'}});
 return new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('fixture server timeout')),15000);server.stdout.on('data',data=>{const match=data.toString().match(/ready: (http:\/\/127\.0\.0\.1:\d+)/);if(match){clearTimeout(timeout);resolve(match[1])}});server.on('error',reject)});
}
async function json(route,body){const response=await fetch(url+route,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+main,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});assert(response.ok,'fixture API '+route+': '+response.status);return response.json()}
async function until(check,label,timeout=20000){const end=Date.now()+timeout;while(Date.now()<end){const value=await check();if(value)return value;await new Promise(r=>setTimeout(r,100))}throw Error('timeout: '+label)}
(async()=>{
 execFileSync(process.execPath,['--check',preload],{windowsHide:true});
 url=await start();main=(await (await fetch(url+'/api/bootstrap')).json()).token;
 browser=await chromium.launch({channel:'msedge',headless:true});const app=await browser.newPage({viewport:{width:1280,height:940}}),errors=[];app.on('pageerror',e=>errors.push(e.message));
 await app.goto(url+'/#sync');await app.getByRole('heading',{name:'尚未连接',exact:true}).waitFor();await app.locator('#desktopLogin').click();
 await until(async()=>{const status=await json('/api/chaoxing/desktop/status');assert.equal(status.last_error,'');return status.qr_ready},'fixture QR');
 await app.locator('#desktopQR').waitFor({state:'visible'});await app.waitForFunction(()=>document.querySelector('#desktopQR')?.naturalWidth>0);
 await app.screenshot({path:path.join(root,'artifacts/desktop-sync-qr-demo.png'),fullPage:true});
 const qr=await fetch(url+'/api/chaoxing/desktop/qr',{headers:{Authorization:'Bearer '+main}});assert.equal(qr.status,200);assert(Buffer.from(await qr.arrayBuffer()).subarray(0,4).equals(Buffer.from([137,80,78,71])));
 if(recovery){
  await until(async()=>{const status=await json('/api/chaoxing/desktop/status');assert.notEqual(status.state,'expired');assert.notEqual(status.state,'error','temporary navigation failure must preserve login and retry');return status.state==='retrying'&&status},'transient failure shown as retrying',25000);
  await app.getByRole('heading',{name:'网络波动，正在重试',exact:true}).waitFor();assert(await app.locator('#desktopResume').isVisible());assert.equal((await json('/api/chaoxing/desktop/status')).session_saved,true);
  await app.screenshot({path:path.join(root,'artifacts/desktop-sync-retry-demo.png'),fullPage:true});
 }
 const first=await until(async()=>{const state=await json('/api/state');return state.messages.filter(m=>m.external?.kind==='course_notice').length===1&&(!chat||state.messages.filter(m=>m.source==='学习通网页 · 聊天正文').length===2)&&state},'first background notice and chat');
 assert.equal(first.tasks.length,0);assert.equal(first.proposals.length,1);assert.equal(first.messages.find(m=>m.external?.kind==='course_notice').external.attachments[0].status,'extracted');if(chat)assert.deepEqual(first.messages.filter(m=>m.source==='学习通网页 · 聊天正文').map(m=>m.text).sort(),['1','。']);assert(first.proposals[0].candidate.requirements.includes('报告甲：第7、9页'));
 const cipher=fs.readFileSync(path.join(temporary,'chaoxing-sync/session.bin'));assert(!cipher.includes(Buffer.from('fixture_auth')));assert(!cipher.includes(Buffer.from('cookies')));
 await app.close();const second=await until(async()=>{const state=await json('/api/state');return state.messages.length===(chat?5:2)&&state},'sync after frontend closed');assert.equal(second.tasks.length,0);
 const previousComplete=(await json('/api/chaoxing/desktop/status')).sources.notice.last_complete_success;assert.equal(previousComplete,null,'the deliberately skipped reference PDF leaves a coverage gap');
 const paused=await json('/api/chaoxing/desktop/pause',{});assert.equal(paused.state,'paused');assert.equal(paused.enabled,false);assert.equal((await fetch(url+'/api/chaoxing/desktop/qr',{headers:{Authorization:'Bearer '+main}})).status,404);
 await json('/api/chaoxing/desktop/resume',{});
 const restored=await until(async()=>{
  const status=await json('/api/chaoxing/desktop/status');assert.notEqual(status.state,'waiting_scan');assert.notEqual(status.state,'expired');assert.notEqual(status.state,'error');
  const {chat:chatSource,notice,task_center:tasks}=status.sources||{};
  return status.state==='partial'&&status.worker_alive===true&&chatSource?.state==='connected'&&chatSource.coverage==='loaded_text'&&chatSource.failed_count===0&&chatSource.pending_count===0&&tasks?.state==='connected'&&tasks.coverage==='complete'&&tasks.failed_count===0&&tasks.pending_count===0&&notice?.state==='partial'&&notice.coverage==='partial'&&notice.attachment_pending_count===2&&notice.failed_count===0&&notice.pending_count===0&&status;
 },'encrypted session restored with the explicit reference-attachment coverage gap');
 assert.equal(restored.sources.notice.last_complete_success,previousComplete,'a healthy partial check cannot advance the last complete success');assert.equal(restored.sources.notice.last_success,previousComplete);
 assert.equal((await json('/api/state')).messages.length,chat?5:2);
 const check=await browser.newPage({viewport:{width:1280,height:940}});check.on('pageerror',e=>errors.push(e.message));await check.goto(url+'/#sync');await check.getByRole('heading',{name:'部分消息待重试',exact:true}).waitFor();await check.locator('#desktopOptions>summary').click();await check.locator('#desktopDiagnostics>summary').click();await check.locator('#desktopCounts').getByText(/已保存 \d+ 条/).waitFor();await check.locator('#desktopLogout').waitFor();if(chat)assert((await check.locator('#desktopSources').textContent()).includes('聊天：已同步'));await check.screenshot({path:path.join(root,'artifacts/desktop-sync-connected-demo.png'),fullPage:true});assert.deepEqual(errors,[]);
 check.once('dialog',dialog=>dialog.accept());await check.locator('#desktopLogout').click();const loggedOut=await until(async()=>{const status=await json('/api/chaoxing/desktop/status');return !status.session_saved&&status.state==='idle'&&status},'account logout');await check.getByRole('heading',{name:'尚未连接',exact:true}).waitFor();assert.equal(loggedOut.session_saved,false);assert.equal((await json('/api/state')).messages.length,chat?5:2);
 const result={passed:true,data:'isolated sanitized fixtures; simulated QR confirmation; no real account',journeys:['official QR element displayed inside app','dedicated headless worker','Windows DPAPI session encryption','notice with DOCX instruction','draft-only intake','periodic notice intake with frontend closed','pause stops capture and hides QR','new worker restores encrypted session','message source counts','account logout preserves evidence','stable notice deduplication','no frontend console errors'],messages:chat?5:2,tasks:0,transientRecovery:recovery,consoleErrors:errors};if(chat)result.journeys.push('multiple chat conversations','digits and symbols retained without tasks','chat polling after frontend closed','stable chat replay after session restore');if(recovery)result.journeys.push('QR in official child frame','three consecutive list network failures','automatic recovery without a new QR scan','detail navigation retried','retry button reuses encrypted session');fs.writeFileSync(path.join(root,'docs/verification',chat?'desktop-chat-browser-result.json':recovery?'desktop-sync-recovery-result.json':'desktop-sync-browser-result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
})().catch(async error=>{console.error(error);if(url&&main){const diagnostic=await json('/api/chaoxing/desktop/status').catch(()=>null);if(diagnostic)console.error(JSON.stringify({state:diagnostic.state,sources:diagnostic.sources}));}const log=path.join(temporary,'fixture-errors.log');if(fs.existsSync(log))console.error(fs.readFileSync(log,'utf8'));process.exitCode=1}).finally(async()=>{
 if(url&&main)await json('/api/chaoxing/desktop/pause',{}).catch(()=>{});
 if(browser)await browser.close();if(server&&server.exitCode===null){const exited=new Promise(r=>server.once('exit',r));if(process.platform==='win32'){try{execFileSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'})}catch{server.kill()}}else server.kill();await exited}
 const target=path.resolve(temporary);assert(target.startsWith(path.resolve(os.tmpdir())+path.sep)&&path.basename(target).startsWith('desktop-sync-test-'));fs.rmSync(target,{recursive:true,force:true});
});
