/* Isolated official-page fixtures. Does not publish or use a platform account. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temporary=fs.mkdtempSync(path.join(os.tmpdir(),'courseinbox-lifecycle-'));
const stageFile=path.join(temporary,'stage.json'),preload=path.join(temporary,'fixture.cjs');
const python=process.env.CI_PYTHON||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
let server,browser,url,token;
fs.writeFileSync(stageFile,'0');
fs.writeFileSync(preload,`
const fs=require('fs'),{chromium}=require('playwright'),launch=chromium.launch.bind(chromium);
const bodies=['','第一次作业，请在2030年10月30日前提交实验报告。','第一次作业，请在2030年10月30日前提交实验报告。','第一次作业截止改为2031年10月30日，其他要求不变。','第一次作业，请在2032年10月30日前提交实验报告。','第一次作业已取消。'];
chromium.launch=async options=>{
 const browser=await launch(options),newContext=browser.newContext.bind(browser);
 browser.newContext=async options=>{
  const context=await newContext(options),originalGet=context.request.get.bind(context.request);
  context.request.get=async(target,options)=>{
   const u=new URL(String(target));
   if(u.hostname!=='notice.chaoxing.com'||!u.pathname.endsWith('/getNoticeDetail'))return originalGet(target,options);
   const n=Number(u.pathname.match(/lifecycle-(\\d+)/)[1]);
   const payload={status:true,msg:{uuid:'$CACG$lifecycle-'+n,idCode:'row-'+n,title:'《示例课程》第一次作业',isRtf:1,rtf_content:'<p>'+bodies[n]+'</p>',ftime:'2026-10-17 12:0'+n,createrName:'测试老师'}};
   return {ok:()=>true,status:()=>200,json:async()=>payload};
  };
  await context.route('**/*',async route=>{
   const u=new URL(route.request().url());let body='';
   if(u.hostname==='i.chaoxing.com')body='<iframe src="https://notice.chaoxing.com/pc/notice/myNotice"></iframe><iframe src="https://mooc2-ans.chaoxing.com/visit/interaction"></iframe>';
   else if(u.hostname==='notice.chaoxing.com'&&u.pathname.endsWith('/getNoticeDetail')){
    const n=Number(u.pathname.match(/lifecycle-(\\d+)/)[1]);
    return route.fulfill({contentType:'application/json',body:JSON.stringify({status:true,msg:{uuid:'$CACG$lifecycle-'+n,idCode:'row-'+n,title:'《示例课程》第一次作业',isRtf:1,rtf_content:'<p>'+bodies[n]+'</p>',ftime:'2026-10-17 12:0'+n,createrName:'测试老师'}})});
   }else if(u.hostname==='notice.chaoxing.com'&&u.pathname.endsWith('/detail'))body='<div id="title"></div><div class="noticeContent"></div>';
   else if(u.hostname==='notice.chaoxing.com'){
    const stage=JSON.parse(fs.readFileSync(${JSON.stringify(stageFile)},'utf8'));
    body='<div class="dataBody" style="min-height:20px">'+Array.from({length:stage},(_,i)=>'<div class="dataBody_item" data-id="row-'+(i+1)+'"><div class="openNotice" data-sendtag="0" data-url="/pc/notice/$CACG$lifecycle-'+(i+1)+'/detail"><span class="notice_title">《示例课程》第一次作业</span><span class="notice_time">2026-10-17 12:0'+(i+1)+'</span></div></div>').join('')+'</div><div class="loadMore loadEnd">已经加载完</div>';
   }else if(u.hostname==='fe.chaoxing.com')body='<div class="conversation-list"></div><div class="null-data">暂无消息</div>';
   else if(u.hostname==='mooc2-ans.chaoxing.com')body='<div class="null-data">暂无课程</div>';
   else return route.abort();
   return route.fulfill({contentType:'text/html;charset=utf-8',body:'<!doctype html><html><body>'+body+'</body></html>'});
  });return context;
 };return browser;
};
`);
async function api(route,body,expected=200){
 const response=await fetch(url+route,{signal:AbortSignal.timeout(15000),method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 assert.equal(response.status,expected,route);return response.json();
}
async function until(check,label,timeout=45000){const deadline=Date.now()+timeout;while(Date.now()<deadline){const value=await check();if(value)return value;await new Promise(resolve=>setTimeout(resolve,200))}throw Error('timeout '+label)}
async function next(stage){
 fs.writeFileSync(stageFile,JSON.stringify(stage));await api('/api/chaoxing/desktop/recheck',{});
 return until(async()=>{const proposals=await api('/api/proposals');return proposals.length===1&&proposals[0]},'stage '+stage);
}
(async()=>{
 const bootstrap="import sys,runpy,faulthandler\nfrom unittest.mock import patch\nfaulthandler.dump_traceback_later(60,repeat=True)\nsys.argv=sys.argv[1:]\nwith patch('courseinbox.core.now_iso',return_value='2026-10-17T12:00:00+08:00'),patch('courseinbox.desktop_alerts.now_iso',return_value='2026-10-17T12:00:00+08:00'):\n runpy.run_path(sys.argv[0],run_name='__main__')";
 server=spawn(python,['-B','-c',bootstrap,path.join(root,'server.py'),'--port','0','--data-dir',temporary],{cwd:root,windowsHide:true,env:{...process.env,NODE_OPTIONS:'--require="'+preload.replaceAll('\\','/')+'"'}});
 let stderr='';server.stderr.on('data',data=>{stderr+=data.toString().slice(0,2000);fs.appendFileSync(path.join(root,'artifacts','lifecycle-diagnostic.log'),data)});
 url=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('server start '+stderr)),20000);server.stdout.on('data',data=>{const found=data.toString().match(/ready: (http:\/\/127\.0\.0\.1:\d+)/);if(found){clearTimeout(timer);resolve(found[1])}});server.on('error',reject)});
 token=(await(await fetch(url+'/api/bootstrap')).json()).token;
 await api('/api/desktop/alerts');await api('/api/chaoxing/desktop/login',{});
 await until(async()=>{const state=await api('/api/chaoxing/desktop/status');return state.sources.notice.last_complete_success},'initial notice inventory');
 const create=await next(1);assert.equal(create.action,'create');assert.equal((await api('/api/tasks')).length,0);
 const events=await api('/api/desktop/alerts');assert.ok(events.events.some(event=>event.kind==='new_pending'));
 await api('/api/desktop/alerts/ack',{ids:events.events.map(event=>event.id)});assert.equal((await api('/api/desktop/alerts')).events.length,0);
 const task=await api('/api/proposals/'+create.id+'/confirm',{});console.log('PASS official JSON capture -> draft -> reminder queue -> confirmed task');
 const duplicate=await next(2);assert.equal(duplicate.target_id,task.id);await api('/api/proposals/'+duplicate.id+'/confirm',{});assert.equal((await api('/api/tasks')).length,1);
 const update=await next(3);assert.equal(update.action,'update');const updated=await api('/api/proposals/'+update.id+'/confirm',{});assert.equal(updated.deadline,'2031-10-30');
 const conflict=await next(4);assert.equal(conflict.action,'conflict');await api('/api/proposals/'+conflict.id+'/confirm',{},400);const kept=await api('/api/proposals/'+conflict.id+'/confirm',{resolution:'current'});assert.equal(kept.deadline,'2031-10-30');
 const cancel=await next(5);const canceled=await api('/api/proposals/'+cancel.id+'/confirm',{});assert.equal(canceled.status,'cancelled');
 const detail=await api('/api/tasks/'+task.id);assert.equal(detail.sources.length,5);assert.equal((await api('/api/tasks')).length,1);
 assert.ok(detail.history.some(item=>item.action==='conflict_keep_current'));
 const report=await api('/api/chaoxing/desktop/acceptance');assert.equal(report.real_acceptance,'pending');assert.equal(report.counts.tasks,1);
 const scoped=(await api('/api/chaoxing/pairing')).token;const denied=await fetch(url+'/api/chaoxing/desktop/acceptance',{headers:{Authorization:'Bearer '+scoped}});assert.equal(denied.status,401);
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'/#sync');await page.locator('#desktopOptions>summary').click();const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'导出检查报告'}).click();
 const file=await downloaded;assert.equal(file.suggestedFilename(),'courseinbox-desktop-check.json');const exported=JSON.parse(fs.readFileSync(await file.path(),'utf8'));assert.equal(exported.real_acceptance,'pending');assert.deepEqual(errors,[]);
 const result={passed:true,data:'isolated simulated official pages; no real account or publication',journeys:['official JSON fallback','draft-only intake','reminder queue and receipt','cross-source duplicate prevention','deadline update','explicit conflict decision','cancellation','source and history retention','read-only acceptance download','scoped token rejection'],real_publication_acceptance:'pending',windows_notification_display:'pending',console_errors:errors};
 fs.mkdirSync(path.join(root,'artifacts/desktop-capture-media'),{recursive:true});fs.writeFileSync(path.join(root,'artifacts/desktop-capture-media/lifecycle.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(async error=>{console.error(error);if(url&&token){try{console.error('isolated fixture status',JSON.stringify(await api('/api/chaoxing/desktop/status')))}catch{}}process.exitCode=1}).finally(async()=>{
 if(browser)await browser.close();if(server){if(url&&token){try{await api('/api/chaoxing/desktop/pause',{})}catch{}}if(server.exitCode===null){const stopped=new Promise(resolve=>server.once('exit',resolve));server.kill();await stopped}}
 const resolved=path.resolve(temporary);if(resolved.startsWith(path.resolve(os.tmpdir())+path.sep)&&path.basename(resolved).startsWith('courseinbox-lifecycle-'))fs.rmSync(resolved,{recursive:true,force:true,maxRetries:5,retryDelay:200});
});
