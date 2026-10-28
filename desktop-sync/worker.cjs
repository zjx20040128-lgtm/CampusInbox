/* Dedicated application browser. No user browser profile or external platform APIs. */
'use strict';
const fs=require('fs'),path=require('path'),readline=require('readline'),crypto=require('crypto');
const {chromium}=require('playwright');
const {ChatCollector}=require('./chat.cjs');
const {TaskCenterCollector}=require('./task-center.cjs');
const {installLiveCapture}=require('./live-capture.cjs');
const directory=path.resolve(process.argv[2]),root=path.resolve(__dirname,'..');
let browser,context,page,timer,active=false,busy=false,everConnected=false,visible=false,generation=0,lastQR=0,phase='browser',failures=0,needRecovery=false,restartBrowserNeeded=false,startedAt=0,rowCursor=0,rowCursorId='',chatCursor='',taskCursor=0,savedSession=null;
let chatCollector,chatTimer,chatEpoch,taskCollector,taskTimer,taskEpoch,heartbeatTimer,taskDetailCursors=[];
const recheckRequested={notice:false,chat:false,task:false},noticeMediaGaps=new Map(),noticeMediaOnly=new Set(),noticeReviewedAt=new Map();
const accepted=new Set(),retryAt=new Map(),retryCount=new Map(),downloads=new Set();
function emit(message){process.stdout.write(JSON.stringify(message)+'\n')}
function status(state,error='',qr_ready=false,details={}){if(active)emit({type:'status',state,error,qr_ready,...details})}
function hashKey(value){return crypto.createHash('sha256').update(String(value||'')).digest('hex')}
function readScanState(){try{const state=JSON.parse(fs.readFileSync(path.join(directory,'scan-state.json'),'utf8'));if(Number.isSafeInteger(state.notice_cursor))rowCursor=state.notice_cursor;if(typeof state.notice_cursor_id==='string')rowCursorId=state.notice_cursor_id;if(typeof state.chat_cursor==='string')chatCursor=state.chat_cursor;if(Number.isSafeInteger(state.task_cursor)&&state.task_cursor>=0)taskCursor=state.task_cursor;if(Array.isArray(state.task_detail_cursors))taskDetailCursors=state.task_detail_cursors.slice(0,1000);for(const entry of (Array.isArray(state.notice_media_gaps)?state.notice_media_gaps:[]).slice(0,10000)){if(Array.isArray(entry)&&/^notice_[A-Za-z0-9_-]{1,180}$/.test(entry[0])&&Number.isSafeInteger(entry[1])&&entry[1]>0)noticeMediaGaps.set(entry[0],Math.min(1000,entry[1]))}for(const id of (Array.isArray(state.notice_media_only)?state.notice_media_only:[]).slice(0,10000)){if(noticeMediaGaps.has(id))noticeMediaOnly.add(id)}for(const entry of (Array.isArray(state.notice_reviewed_at)?state.notice_reviewed_at:[]).slice(-10000)){if(Array.isArray(entry)&&/^notice_[A-Za-z0-9_-]{1,180}$/.test(entry[0])&&Number.isSafeInteger(entry[1])&&entry[1]>0&&entry[1]<=Date.now())noticeReviewedAt.set(entry[0],entry[1])}}catch{}}
function saveScanState(){try{const file=path.join(directory,'scan-state.json'),temporary=file+'.tmp';fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(temporary,JSON.stringify({notice_cursor:rowCursor,notice_cursor_id:rowCursorId,chat_cursor:chatCursor,task_cursor:taskCursor,task_detail_cursors:taskDetailCursors,notice_media_gaps:[...noticeMediaGaps],notice_media_only:[...noticeMediaOnly],notice_reviewed_at:[...noticeReviewedAt].slice(-10000)}));fs.renameSync(temporary,file)}catch{}}
function heartbeat(epoch){if(!active||epoch!==generation)return;emit({type:'heartbeat'});heartbeatTimer=setTimeout(()=>heartbeat(epoch),15000)}
function official(value){try{const u=new URL(value);return u.protocol==='https:'&&(u.hostname==='chaoxing.com'||u.hostname.endsWith('.chaoxing.com'))}catch{return false}}
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function parser(frame){for(const name of ['parser.js','notices.js'])await frame.evaluate(fs.readFileSync(path.join(root,'browser-companion',name),'utf8'))}
function noticeFrame(){return page?.frames().find(frame=>{try{const u=new URL(frame.url());return u.origin==='https://notice.chaoxing.com'&&u.pathname==='/pc/notice/myNotice'}catch{return false}})}
async function authenticated(){return Boolean(noticeFrame()) || Boolean(await page.getByText('收件箱',{exact:true}).count())}
function fault(code){return Object.assign(Error(code),{code})}
function reason(error){
  if(['timeout','network','interrupted','closed','http_429','http_5xx','http_error','dom','expired'].includes(error?.code))return error.code;
  if(error?.name==='TimeoutError')return 'timeout';
  const text=String(error?.message||'');
  if(/closed|has been closed/i.test(text))return 'closed';
  if(/detached|interrupted/i.test(text))return 'interrupted';
  return /net::|network/i.test(text)?'network':'unexpected';
}
async function loginRequired(target){
  const frames=typeof target.frames==='function'?target.frames():[target];
  for(const frame of frames){
    try{
      const u=new URL(frame.url());if(!official(u.href))continue;
      if(u.hostname==='passport2.chaoxing.com'&&u.pathname.startsWith('/login'))return true;
      const image=frame.locator('#quickCode');if(await image.count()>0&&await image.first().isVisible())return true;
    }catch{}
  }
  return false;
}
async function load(target,url,epoch,navigationStage,selector='',contentStage=navigationStage){
  if(!official(url))throw fault('dom');
  for(let attempt=0;attempt<3;attempt++){
    if(!active||epoch!==generation)throw fault('interrupted');
    try{
      phase=navigationStage;const response=await target.goto(url,{waitUntil:'domcontentloaded',timeout:20000});
      if(await loginRequired(target))return false;
      const code=response?.status();if(code>=400)throw fault(code===429?'http_429':code>=500?'http_5xx':'http_error');
      if(!official(target.url()))throw fault('network');
      if(selector){phase=contentStage;await target.locator(selector).first().waitFor({timeout:12000})}
      return true;
    }catch(error){const code=reason(error);if(code==='expired'||code==='closed'||code==='interrupted'||attempt===2||!active||epoch!==generation)throw error;await delay(500*(attempt+1))}
  }
}
async function ready(){
  for(let attempt=0;attempt<12&&active;attempt++){
    if(await authenticated()||await loginRequired(page))return;await delay(250);
  }
}
async function showQR(expired=false){
  if(!official(page.url()))throw fault('network');
  for(const frame of page.frames()){
    if(!official(frame.url()))continue;
    const image=frame.locator('#quickCode');
    if(await image.count()&&await image.isVisible()&&await image.evaluate(node=>node.complete&&node.naturalWidth>0)){
      if(Date.now()-lastQR>10000){await image.screenshot({path:path.join(directory,'qr.png'),timeout:5000});lastQR=Date.now()}
      status(expired?'expired':'waiting_scan',expired?'expired':'',!expired);return;
    }
  }
  if(expired){status('expired','expired');return}
  if(Date.now()-startedAt<30000){status('connecting');return}
  throw fault('dom');
}
async function inbox(){
  let frame=noticeFrame();if(frame)return frame;
  const link=page.getByText('收件箱',{exact:true});
  if(!await link.count())return null;
  await link.first().click({timeout:5000});
  for(let i=0;i<20&&active;i++){frame=noticeFrame();if(frame)return frame;await delay(250)}
  return null;
}
async function expandNoticeList(frame,epoch){
  let complete=false;
  for(let pageIndex=0;pageIndex<8&&active&&epoch===generation;pageIndex++){
    const state=await frame.evaluate(()=>({count:document.querySelectorAll('.dataBody_item[data-id]').length,end:Boolean(document.querySelector('.loadMore.loadEnd')),button:Boolean(document.querySelector('.loadMore .loadText'))}));
    if(state.end){complete=true;break}
    if(state.count>=200)break;
    if(!state.button)break;
    await frame.evaluate(()=>{const box=document.querySelector('.dataCon');if(box)box.scrollTop=box.scrollHeight});
    try{const button=frame.locator('.loadMore .loadText');if(!await button.isVisible())break;await button.click({timeout:5000})}
    catch{break}
    try{await frame.waitForFunction(before=>document.querySelectorAll('.dataBody_item[data-id]').length>before||Boolean(document.querySelector('.loadMore.loadEnd')),state.count,{timeout:7000})}
    catch{break}
  }
  if(!complete)complete=await frame.evaluate(()=>Boolean(document.querySelector('.loadMore.loadEnd')));
  return {rows:await frame.evaluate(()=>CourseInboxNotices.extractList(document,location.href)),complete};
}
async function waitForNoticeContent(target,epoch,fallbackTitle='',timeout=20000){
  const started=Date.now(),deadline=started+timeout;let previous='',stable=0;
  while(active&&epoch===generation&&Date.now()<deadline){
    const snapshot=await target.evaluate(fallbackTitle=>{
      const content=document.querySelector('.noticeContent');
      const title=document.querySelector('#title')?.textContent?.trim()||'',text=content?.innerText?.trim()||'';
      const metadata=Boolean(document.querySelector('.createTime')?.textContent?.trim()&&document.querySelector('.createName')?.textContent?.trim());
      return {container:Boolean(content),title:title||fallbackTitle,text,attachments:content?.querySelectorAll('iframe.attach-insertCloud[name]').length||0,media_count:content?.querySelectorAll('img,video,audio,canvas,object,embed,iframe:not(.attach-insertCloud)').length||0,empty_ready:Boolean(content&&title&&metadata&&document.readyState==='complete'&&!text&&!content.querySelector('img,video,audio,canvas,object,embed,iframe'))};
    },fallbackTitle);
    if(snapshot.title&&(snapshot.text||snapshot.attachments>0||snapshot.media_count>0||snapshot.empty_ready)){
      const signature=hashKey(JSON.stringify(snapshot));
      if(signature===previous)stable++;else stable=0;
      previous=signature;
      if(stable>=4&&(!snapshot.empty_ready||Date.now()-started>=5000))return snapshot;
    }else{previous='';stable=0}
    await delay(400);
  }
  if(!active||epoch!==generation)throw fault('interrupted');
  throw fault('timeout');
}
async function readNoticeData(target,row,epoch){
  if(!active||epoch!==generation)throw fault('interrupted');
  const api=require('../browser-companion/notices.js').detailDataURL(row.url);
  if(!api)throw fault('dom');
  const response=await target.request.get(api,{timeout:10000,maxRedirects:0});
  if(response.status()===401)throw fault('expired');
  if(!response.ok())throw fault(response.status()===429?'http_429':response.status()>=500?'http_5xx':'http_error');
  const payload=await response.json();
  if(!active||epoch!==generation)throw fault('interrupted');
  await parser(target);
  const job=await target.evaluate(({payload,row})=>CourseInboxNotices.extractData(document,payload,row,undefined,{inlineImages:true}),{payload,row});
  if(!job)throw fault('dom');
  delete job.empty_body_ready;
  return job;
}
async function saveSession(){
  const data=await context.storageState();
  const session={cookies:data.cookies.filter(c=>c.domain.replace(/^\./,'')==='chaoxing.com'||c.domain.endsWith('.chaoxing.com')),origins:data.origins.filter(o=>official(o.origin))};
  savedSession=session;if(active)emit({type:'session',session});return session;
}
function watchMainPage(owned,epoch){
  const main=page;
  main.on('close',()=>{
    if(!active||epoch!==generation||browser!==owned||page!==main)return;
    page=undefined;needRecovery=true;restartBrowserNeeded=false;
    status('retrying','network',false,{stage:'browser',reason:'closed',retry_in:10});
  });
}
async function createBrowser(epoch,session,headless){
  const launched=await chromium.launch({channel:'msedge',headless});
  if(!active||epoch!==generation){await launched.close();return false}
  browser=launched;
  launched.on('disconnected',()=>{
    if(!active||epoch!==generation||browser!==launched)return;
    needRecovery=true;restartBrowserNeeded=true;
    status('retrying','network',false,{stage:'browser',reason:'closed',retry_in:10});
  });
  context=await launched.newContext({viewport:{width:1040,height:760},storageState:session||undefined,acceptDownloads:false});
  const watchedContext=context;
  try{await installLiveCapture(context,event=>{if(active&&epoch===generation&&context===watchedContext)requestDOMCapture(event)})}catch{/* Timed checks remain available if injection is unavailable. */}
  context.on('close',()=>{
    if(!active||epoch!==generation||browser!==launched||!page)return;
    needRecovery=true;restartBrowserNeeded=true;
    status('retrying','network',false,{stage:'browser',reason:'closed',retry_in:10});
  });
  page=await context.newPage();page.setDefaultTimeout(8000);watchMainPage(launched,epoch);return true;
}
async function disposeBrowser(){
  clearTimeout(chatTimer);chatTimer=undefined;chatEpoch=undefined;
  clearTimeout(taskTimer);taskTimer=undefined;taskEpoch=undefined;
  const previousChat=chatCollector;chatCollector=undefined;
  if(previousChat){chatCursor=previousChat.cursor||chatCursor;saveScanState();await previousChat.close().catch(()=>{})}
  const previousTasks=taskCollector;taskCollector=undefined;
  if(previousTasks){taskCursor=previousTasks.cursor;taskDetailCursors=[...(previousTasks.detailCursors||[])];saveScanState();await previousTasks.close().catch(()=>{})}
  for(const controller of downloads)controller.abort();
  const current=browser;browser=context=page=undefined;
  if(current)await current.close().catch(()=>{});
}
function createChatCollector(epoch){
  let current;
  current=new ChatCollector({context,accepted,cursor:chatCursor,isCurrent:()=>active&&epoch===generation&&chatCollector===current,onMessage:job=>emit({type:'chat',job}),onStatus:value=>{
    if(chatCollector!==current)return;
    if(typeof value.cursor==='string'){chatCursor=value.cursor;saveScanState()}
    if(value.reason==='closed'){needRecovery=true;restartBrowserNeeded=true}
    const details={...value};delete details.cursor;
    source('chat',value.state,value.error,details);
  }});
  chatCollector=current;return current;
}
function createTaskCollector(epoch){
  let current;
  current=new TaskCenterCollector({context,accepted,cursor:taskCursor,detailCursors:taskDetailCursors,isCurrent:()=>active&&epoch===generation&&taskCollector===current,onInventory:value=>{if(active&&epoch===generation&&taskCollector===current)emit({type:'task_inventory',...value})},onMessage:async job=>{if(job.kind==='checkin_activity'){if(active&&epoch===generation&&taskCollector===current)emit({type:'checkin_activity',job});return}const prepared=await prepare(structuredClone(job));if(active&&epoch===generation&&taskCollector===current)emit({type:'task_center',job:prepared})},onStatus:value=>{
    if(taskCollector!==current)return;
    if(Array.isArray(value.detail_cursors))taskDetailCursors=value.detail_cursors;
    if(Number.isSafeInteger(value.cursor)){taskCursor=value.cursor;saveScanState()}
    const details={...value};delete details.cursor;delete details.detail_cursors;
    source('task_center',value.state,value.error,details);
  }});
  taskCollector=current;return current;
}
async function ensureBrowser(epoch){
  if(!active||epoch!==generation)throw fault('interrupted');
  if(!browser||!browser.isConnected()||restartBrowserNeeded){
    await disposeBrowser();
    if(!await createBrowser(epoch,savedSession,true))throw fault('interrupted');
    visible=false;restartBrowserNeeded=false;needRecovery=true;
  }else if(!page||page.isClosed()){
    try{page=await context.newPage();page.setDefaultTimeout(8000);watchMainPage(browser,epoch)}
    catch{
      restartBrowserNeeded=true;await disposeBrowser();
      if(!await createBrowser(epoch,savedSession,true))throw fault('interrupted');
      visible=false;restartBrowserNeeded=false;needRecovery=true;
    }
  }
}
async function download(url){
  const {safeImageURL}=require('../browser-companion/notices.js');
  if(!url||(!/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(url)&&safeImageURL(url)!==url))throw Error('source');
  const controller=new AbortController();downloads.add(controller);const timeout=setTimeout(()=>controller.abort(),15000);
  try{
    const response=await fetch(url,{signal:controller.signal,credentials:'omit',redirect:'error'});
    if(!response.ok||Number(response.headers.get('content-length'))>8*1024*1024)throw Error('download');
    const reader=response.body.getReader(),chunks=[];let length=0;
    while(true){const {value,done}=await reader.read();if(done)break;length+=value.length;if(length>8*1024*1024){await reader.cancel();throw Error('large')}chunks.push(Buffer.from(value))}
    return Buffer.concat(chunks);
  }finally{clearTimeout(timeout);downloads.delete(controller)}
}
async function prepare(job){
  let remaining=8*1024*1024;
  for(const attachment of job.attachments||[]){
    attachment.text='';attachment.error='';
    const instruction=attachment.kind==='inline_image'||/说明|要求|作业|任务|通知|安排|instructions?|assignment|requirements?|guidelines?/i.test(attachment.name)||/\.docx$/i.test(attachment.name);
    if(!instruction){attachment.status='skipped';attachment.error='原文件已关联，未自动提取文字。';continue}
    if(!/\.(docx|pdf|txt|md|png|jpe?g|bmp|webp)$/i.test(attachment.name)||!attachment.url||attachment.size>remaining){attachment.status='skipped';attachment.error='附件格式、链接或大小不支持自动读取。';continue}
    if(!active)throw Error('paused');
    try{const bytes=await download(attachment.url);if(bytes.length>remaining)throw Error('large');remaining-=bytes.length;if(!active)throw Error('paused');attachment.content_base64=bytes.toString('base64')}
    catch{attachment.status='failed';attachment.error='说明附件下载失败，通知原文先保存。'}
  }
  return job;
}
function source(name,state,error='',details={}){if(active)emit({type:'source',source:name,state,error,...details})}
function requestDOMCapture(event){
  if(!active)return;
  if(event.kind==='chat'&&chatCollector){
    chatCollector.prioritize(event.conversations);clearTimeout(chatTimer);
    if(chatEpoch)recheckRequested.chat=true;else chatTimer=setTimeout(()=>scanChats(generation).catch(()=>{}),250);
  }else if(event.kind==='notice'){
    clearTimeout(timer);if(busy)recheckRequested.notice=true;else timer=setTimeout(()=>scan(generation).catch(()=>{}),250);
  }else if(event.kind==='task'&&taskCollector){
    clearTimeout(taskTimer);if(taskEpoch)recheckRequested.task=true;else taskTimer=setTimeout(()=>scanTasks(generation).catch(()=>{}),250);
  }
}
async function scanChats(epoch){
  if(!active||epoch!==generation||chatEpoch||!chatCollector)return;
  const current=chatCollector,token={};chatEpoch=token;
  try{await current.sweep()}finally{
    if(chatEpoch===token)chatEpoch=undefined;
    if(active&&epoch===generation&&current===chatCollector){const next=recheckRequested.chat?1000:10000;recheckRequested.chat=false;chatTimer=setTimeout(()=>scanChats(epoch),next)}
  }
}
async function scanTasks(epoch){
  if(!active||epoch!==generation||taskEpoch||!taskCollector)return;
  const current=taskCollector,token={};taskEpoch=token;
  try{await current.sweep()}finally{
    if(taskEpoch===token)taskEpoch=undefined;
    if(active&&epoch===generation&&current===taskCollector){const next=recheckRequested.task?1000:30000;recheckRequested.task=false;taskTimer=setTimeout(()=>scanTasks(epoch),next)}
  }
}
async function scan(epoch){
  if(busy||!active||epoch!==generation)return;const token={};busy=token;let next=everConnected?15000:2000;
  try{
    await ensureBrowser(epoch);
    if(needRecovery){await load(page,'https://i.chaoxing.com',epoch,'portal_navigation');needRecovery=false}
    phase='login_ready';await ready();
    if(!await authenticated()){
      if(await loginRequired(page)){await showQR(everConnected);return}
      if(!everConnected&&Date.now()-startedAt<20000){status('connecting');return}
      throw fault('dom');
    }
    if(!everConnected){
      phase='session_save';const session=await saveSession();
      if(visible){await disposeBrowser();if(!await createBrowser(epoch,session,true))throw fault('interrupted');await load(page,'https://i.chaoxing.com',epoch,'portal_navigation');visible=false;await ready()}
      everConnected=true;next=15000;
    }
    if(!chatCollector){createChatCollector(epoch);scanChats(epoch).catch(()=>{})}
    if(!taskCollector){createTaskCollector(epoch);scanTasks(epoch).catch(()=>{})}
    source('notice','syncing','',{checked_count:0,captured_count:0,failed_count:0,pending_count:retryAt.size});phase='list_ready';const frame=await inbox();if(!frame)throw fault('dom');
    if(!await load(frame,frame.url(),epoch,'list_navigation','.dataBody_item,.dataBody','list_ready')){status('expired','expired');return}
    if(!noticeFrame())throw fault('dom');
    await parser(frame);const listing=await expandNoticeList(frame,epoch),rows=listing.rows;
    let detail,checked=0,captured=0,revisited=0,partialCount=0,partial=false,expired=false,partialReason='',partialStage='';const capturedIds=new Set(),scanDeadline=Date.now()+90000;status('syncing');
    try{
      const cursorIndex=rows.findIndex(row=>hashKey(row.id||row.url)===rowCursorId);
      const sweepStart=rows.length?(cursorIndex>=0?(cursorIndex+1)%rows.length:rowCursor%rows.length):0;
      for(let offset=0;offset<rows.length;offset++){
        if(checked>=25||Date.now()>=scanDeadline||!active||epoch!==generation)break;
        const index=(sweepStart+offset)%rows.length,row=rows[index];rowCursor=(index+1)%rows.length;
        rowCursorId=hashKey(row.id||row.url);saveScanState();
        const id='notice_'+new URL(row.url).pathname.split('/')[3].replace(/^\$[A-Z]+\$/,'');
        if(noticeMediaOnly.has(id)||(retryAt.get(id)||0)>Date.now())continue;
        // Revisit a few accepted details to discover late images without starving new notices.
        if(accepted.has(id)){
          const reviewed=noticeReviewedAt.get(id)||0;
          if(revisited>=5||(reviewed&&Date.now()-reviewed<600000))continue;
          revisited++;accepted.delete(id);
        }
        checked++;
        source('notice','syncing','',{checked_count:checked,captured_count:captured,stage:'detail_navigation'});
        try{
          if(!detail)detail=await context.newPage();
          if(!await load(detail,row.url,epoch,'detail_navigation')){expired=true;source('notice','expired','expired');status('expired','expired');break}
          if(new URL(detail.url()).origin!=='https://notice.chaoxing.com')throw fault('dom');
          phase='detail_content';let content,job;
          try{content=await waitForNoticeContent(detail,epoch,row.title,6000)}
          catch(error){
            if(reason(error)!=='timeout')throw error;
            phase='detail_data';
            try{job=await readNoticeData(detail,row,epoch)}
            catch(fallbackError){if(['closed','interrupted','expired'].includes(reason(fallbackError)))throw fallbackError;phase='detail_content';content=await waitForNoticeContent(detail,epoch,row.title,14000)}
          }
          if(!job){phase='detail_parse';await parser(detail);job=await detail.evaluate(row=>CourseInboxNotices.extractDetail(document,row,undefined,{inlineImages:true}),row)}
          const mediaPending=job?.media_pending_count??content?.media_count??0;
          if(mediaPending>0)noticeMediaGaps.set(id,mediaPending);else noticeMediaGaps.delete(id);
          saveScanState();
          if(!job&&mediaPending>0){noticeMediaOnly.add(id);saveScanState();continue}
          if(!job)throw fault('dom');
          const prepared=await prepare(job);if(active&&epoch===generation){emit({type:'notice',job:prepared});captured++;capturedIds.add(id);retryAt.delete(id);retryCount.delete(id);noticeReviewedAt.delete(id);noticeReviewedAt.set(id,Date.now());if(noticeReviewedAt.size>10000)noticeReviewedAt.delete(noticeReviewedAt.keys().next().value);saveScanState()}
        }catch(error){
          if(!active||epoch!==generation)break;
          if(reason(error)==='expired'){expired=true;source('notice','expired','expired',{stage:phase,reason:'expired'});status('expired','expired');break}
          partial=true;partialCount++;partialReason=reason(error);partialStage=phase;const attempts=(retryCount.get(id)||0)+1;retryCount.set(id,attempts);retryAt.set(id,Date.now()+Math.min(300000,15000*2**Math.min(attempts-1,5)));
          if(partialReason==='closed'&&detail){await detail.close().catch(()=>{});detail=undefined}
          source('notice','partial','notice',{stage:partialStage,reason:partialReason,failed_count:partialCount,pending_count:retryAt.size});status('partial','notice',false,{stage:partialStage,reason:partialReason});
        }
      }
    }finally{if(detail)await detail.close().catch(()=>{})}
    const pendingCount=Math.max(retryAt.size,rows.filter(row=>{const id='notice_'+new URL(row.url).pathname.split('/')[3].replace(/^\$[A-Z]+\$/,'');return !accepted.has(id)&&!capturedIds.has(id)&&!noticeMediaOnly.has(id)}).length);
    const mediaCount=[...noticeMediaGaps.values()].reduce((sum,value)=>sum+value,0);
    const issues=rows.flatMap((row,index)=>{const id='notice_'+new URL(row.url).pathname.split('/')[3].replace(/^\$[A-Z]+\$/,'');return retryAt.has(id)||noticeMediaGaps.has(id)?[{notice_index:index+1}]:[]}).slice(0,10);
    partial=partial||pendingCount>0||!listing.complete||mediaCount>0;
    if(active&&epoch===generation&&!expired){phase='session_save';await saveSession();failures=0;const issue=mediaCount&&!pendingCount&&listing.complete&&!partialCount?'coverage':partial?'notice':'';source('notice',partial?'partial':'connected',issue,{checked:true,checked_count:checked,captured_count:captured,failed_count:partialCount,pending_count:pendingCount+(!listing.complete?1:0),media_pending_count:mediaCount,coverage:partial?'partial':'complete',issues,stage:partial?(partialStage||'list_ready'):'',reason:partialReason});status(partial?'partial':'connected',issue,false,{checked:true})}
  }catch(error){
    if(active&&epoch===generation){
      const code=reason(error);
      if(code==='expired'){source('notice','expired','expired',{stage:phase,reason:code});status('expired','expired',false,{stage:phase,reason:code})}
      else{source('notice','retrying',code==='dom'?'dom':'network',{stage:phase,reason:code});needRecovery=true;if(code==='closed')restartBrowserNeeded=true;next=Math.min(60000,10000*2**Math.min(failures++,3));status('retrying',code==='dom'?'dom':'network',false,{stage:phase,reason:code,retry_in:next/1000})}
    }
  }finally{if(busy===token)busy=false;if(active&&epoch===generation){if(recheckRequested.notice){next=0;recheckRequested.notice=false}timer=setTimeout(()=>scan(epoch),next)}}
}
function requestRecheck(){
  if(!active)return;
  retryAt.clear();retryCount.clear();for(const id of accepted)if(id.startsWith('notice_'))accepted.delete(id);noticeReviewedAt.clear();noticeMediaOnly.clear();saveScanState();
  clearTimeout(timer);clearTimeout(chatTimer);clearTimeout(taskTimer);
  if(chatCollector)chatCollector.navigate=true;
  recheckRequested.notice=Boolean(busy);recheckRequested.chat=Boolean(chatEpoch);recheckRequested.task=Boolean(taskEpoch);
  if(!busy)scan(generation).catch(()=>{});
  if(!chatEpoch)scanChats(generation).catch(()=>{});
  if(!taskEpoch)scanTasks(generation).catch(()=>{});
}
async function close(){
  active=false;generation++;busy=false;clearTimeout(timer);clearTimeout(heartbeatTimer);timer=heartbeatTimer=undefined;needRecovery=false;restartBrowserNeeded=false;await disposeBrowser();
}
async function start(command){
  await close();active=true;everConnected=false;lastQR=0;failures=0;needRecovery=false;restartBrowserNeeded=false;rowCursor=0;rowCursorId='';chatCursor='';taskCursor=0;savedSession=command.session||null;startedAt=Date.now();visible=command.visible===true;const epoch=generation;
  noticeMediaGaps.clear();noticeMediaOnly.clear();noticeReviewedAt.clear();taskDetailCursors=[];readScanState();accepted.clear();for(const id of command.accepted||[])accepted.add(id);retryAt.clear();retryCount.clear();recheckRequested.notice=recheckRequested.chat=recheckRequested.task=false;status('connecting');heartbeat(epoch);
  try{
    if(!await createBrowser(epoch,savedSession,!visible))return;
    try{await load(page,'https://i.chaoxing.com',epoch,'portal_navigation')}catch{needRecovery=true}
    if(active&&epoch===generation)await scan(epoch);
  }catch{status('error','runtime')}
}
let starting=Promise.resolve();
readline.createInterface({input:process.stdin}).on('line',line=>{
  let command;try{command=JSON.parse(line)}catch{return}
  if(command.type==='start')starting=starting.then(()=>start(command));
  else if(command.type==='accepted'){if(taskCollector)taskCollector.recordReceipt(command.id,command.media_complete===true);if(command.complete){accepted.add(command.id);retryAt.delete(command.id);retryCount.delete(command.id)}else retryAt.set(command.id,Date.now()+300000)}
  else if(command.type==='recheck')requestRecheck();
  else if(command.type==='repair_tasks'&&active&&taskCollector){taskCollector.requestRepair(command.keys);clearTimeout(taskTimer);if(taskEpoch)recheckRequested.task=true;else scanTasks(generation).catch(()=>{})}
  else if(command.type==='repair_sections'&&active&&taskCollector){taskCollector.requestRepairSections(command.keys);clearTimeout(taskTimer);if(taskEpoch)recheckRequested.task=true;else scanTasks(generation).catch(()=>{})}
  else if(command.type==='close')shutdown();
}).on('close',shutdown);
let stopping=false;
function shutdown(){if(stopping)return;stopping=true;close().finally(()=>starting.finally(()=>close().finally(()=>process.exit(0))))}
process.on('SIGTERM',shutdown);
