'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process');
const runtime=path.join(os.homedir(),'.cache','codex-runtimes','codex-primary-runtime','dependencies');
let playwright;try{playwright=require('playwright');}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;playwright=require(path.join(runtime,'node','node_modules','playwright'));}
const root=path.resolve(__dirname,'..'),artifacts=path.join(root,'artifacts'),key='courseinbox.phone-reminders.v1';
fs.mkdirSync(artifacts,{recursive:true});
const directory=fs.mkdtempSync(path.join(artifacts,'phone-reminders-browser-'));
const python=process.env.CI_PYTHON||(fs.existsSync(path.join(runtime,'python','python.exe'))?path.join(runtime,'python','python.exe'):'python');
let server,browser,mainUrl,mainToken,phoneUrl,heldRelease;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,message,timeout=10000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await sleep(100);}throw Error(message);}
async function api(endpoint,body){const response=await fetch(mainUrl+endpoint,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+mainToken,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});assert.ok(response.ok,endpoint+' returned HTTP '+response.status);return response.json();}
async function phonePoll(token){const response=await fetch(phoneUrl+'v1/alerts',{headers:{Authorization:'Bearer '+token}});assert.ok(response.ok,'device poll returned HTTP '+response.status);return response.json();}
async function ingest(text){return api('/api/messages',{text,source:'学习通课程通知',captured_at:new Date().toISOString(),mode:'rules'});}
async function stored(page){return page.evaluate(key=>JSON.parse(localStorage.getItem(key)||'null'),key);}
async function pair(page,name){const code=(await api('/api/mobile-reminders/pairing',{})).code;await page.locator('#pairCode').fill(code);await page.locator('#phoneName').fill(name);await page.locator('#connect').click();await page.waitForFunction(key=>!!JSON.parse(localStorage.getItem(key)||'null')?.session?.token,key);const state=await stored(page);assert.ok(state.enabled&&state.session.token!==mainToken,'pairing stores an independent device credential and enables receiving');await page.locator('#connectionStatus').filter({hasText:/已连接|配对成功/}).waitFor();return state.session;}
async function delivered(page,marker,session){await page.locator('#history').filter({hasText:marker}).waitFor();await until(async()=>{const state=await stored(page);return state.pending.length===0;},'browser did not persist successful ACK');const remaining=(await phonePoll(session.token)).events;assert.ok(!remaining.some(event=>event.body.includes(marker)),'acknowledged alert must not be pending on the real server');}
async function layout(page){for(const width of [320,390]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,width+'px phone page must not overflow');}}
async function holdAcrossTabs(pages,marker){
 const held=[];
 for(const page of pages)await page.route('**/v1/stream',async route=>{
  const response=await page.request.get(phoneUrl+'v1/alerts',{headers:{Authorization:route.request().headers().authorization}}),batch=await response.json(),event=batch.events.find(event=>event.body.includes(marker));
  if(!event){try{await route.fulfill({status:200,contentType:'text/event-stream',body:'data: '+JSON.stringify(batch)+'\n\n'});}catch(error){if(!/already handled|closed|canceled|cancelled|aborted/i.test(error.message))throw error;}return;}
  await new Promise(resolve=>{held.push({page,event,release:async()=>{try{await route.fulfill({status:200,contentType:'text/event-stream',body:'data: '+JSON.stringify(batch)+'\n\n'});}catch(error){if(!/already handled|closed|canceled|cancelled|aborted/i.test(error.message))throw error;}finally{resolve();}}});});
 });
 heldRelease=async()=>{for(const response of held)await response.release();};
 return {held,async ready(){await until(()=>held.some(response=>response.page===pages[1]),'second tab did not hold a real issued reminder');},async release(){await heldRelease();heldRelease=null;for(const page of pages)await page.unroute('**/v1/stream');}};
}
async function exercise(browser,label,full){
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 // Run production streaming and cancellation, accelerating only reconnect backoff.
 await context.addInitScript(()=>{const original=window.setTimeout;window.setTimeout=function(fn,delay,...args){return original.call(this,fn,delay===5000?1000:delay,...args);};});
 const page=await context.newPage();page.setDefaultTimeout(10000);const errors=[],acknowledged=[],browserRequests=[];page.on('request',r=>browserRequests.push(new URL(r.url()).pathname));
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(new URL(request.url()).pathname==='/v1/ack'){const body=request.postDataJSON();acknowledged.push(...body.ids);}});
 try{
  const navigation=await page.goto(phoneUrl);assert.equal(navigation.status(),200,'restricted listener must serve the no-install phone page');
  const copy=await page.locator('body').innerText();assert.match(copy,/电脑保持运行/);assert.match(copy,/开启后台提醒后/);assert.match(copy,/首次点击授权通知/);assert.equal(await page.locator('a[href$=".apk"]').count(),0,'phone browser flow does not require an APK');
  await layout(page);await page.locator('#soundToggle').click();assert.equal((await stored(page)).sound,true,'sound is enabled only by an explicit click');await page.locator('#soundToggle').click();assert.equal((await stored(page)).sound,false);
  const session=await pair(page,label+' 浏览器手机 <img src=x onerror="window.phoneNameXss=1">');
  const devices=(await api('/api/mobile-reminders/status')).devices;assert.ok(devices.some(device=>device.id===session.device_id),'real pairing is visible on the computer');
  const marker=label+' 普通消息A';const text=marker+'：材料已更新。<img src=x onerror="window.phoneReminderXss=1"> https://untrusted.example/';
  const ingested=await ingest(text);assert.equal(ingested.proposals.length,0,'fictional ordinary message should not depend on task extraction');
  await delivered(page,marker,session);assert.equal(browserRequests.filter(p=>p==='/v1/alerts').length,0,'phone browser must not poll alerts');assert.equal(browserRequests.filter(p=>p==='/v1/stream').length,1,'new messages use the existing persistent connection');assert.equal(await page.locator('#history .event').count(),1,'new ordinary message creates one local reminder');
  assert.equal(await page.locator('#history img, #history script, #history a').count(),0,'source HTML and URLs remain inert text');assert.equal(await page.evaluate(()=>window.phoneReminderXss||window.phoneNameXss||false),false);
  const raw=await page.evaluate(key=>localStorage.getItem(key),key);assert.ok(!raw.includes(mainToken),'phone storage must never contain the computer main access token');
  await page.reload();await page.locator('#history').filter({hasText:marker}).waitFor();await page.locator('#connectionStatus').filter({hasText:'已连接'}).waitFor();assert.equal(await page.locator('#history .event').count(),1,'reload retains history without duplicate reminders');
  if(full){
   await page.locator('#toggleReceive').click();await page.locator('#connectionStatus').filter({hasText:'已停止接收'}).waitFor();
   const heldMarker=label+' 停止代次隔离消息';await ingest(heldMarker+'：材料备注已更新。');await sleep(150);assert.ok(!(await page.locator('#history').innerText()).includes(heldMarker),'stopped page does not collect new reminders');
   let heldResolve;const held=new Promise(resolve=>heldResolve=resolve);let heldEvent;
   await page.route('**/v1/stream',async route=>{
    const response=await page.request.get(phoneUrl+'v1/alerts',{headers:{Authorization:route.request().headers().authorization}});const batch=await response.json();heldEvent=batch.events.find(event=>event.body.includes(heldMarker));
    assert.ok(heldEvent,'held response contains a real issued reminder');
    await new Promise(resolve=>{heldRelease=async()=>{try{await route.fulfill({status:200,contentType:'text/event-stream',body:'data: '+JSON.stringify(batch)+'\n\n'});}catch(error){if(!/already handled|closed|canceled|cancelled|aborted/i.test(error.message))throw error;}finally{resolve();}};heldResolve();});
   });
   await page.locator('#toggleReceive').click();await Promise.race([held,sleep(10000).then(()=>{throw Error('resumed poll was not held');})]);
   await page.locator('#toggleReceive').click();await page.locator('#connectionStatus').filter({hasText:'已停止接收'}).waitFor();
   await heldRelease();heldRelease=null;await sleep(350);
   assert.ok(!(await page.locator('#history').innerText()).includes(heldMarker),'late response cannot deliver after stop');assert.ok(!acknowledged.includes(heldEvent.id),'late response cannot ACK after stop');assert.equal((await stored(page)).enabled,false);
   await page.unroute('**/v1/stream');await page.locator('#toggleReceive').click();await delivered(page,heldMarker,session);assert.equal(await page.locator('#history .event').count(),2,'resume receives retained event exactly once');
   const second=await context.newPage();second.setDefaultTimeout(10000);second.on('pageerror',error=>errors.push(error.message));second.on('request',request=>{if(new URL(request.url()).pathname==='/v1/ack')acknowledged.push(...request.postDataJSON().ids);});
   await second.goto(phoneUrl);await second.locator('#connectionStatus').filter({hasText:'已连接'}).waitFor();
   await page.locator('#toggleReceive').click();await second.locator('#connectionStatus').filter({hasText:'已停止接收'}).waitFor();
   const crossMarker=label+' 跨标签页停止消息',cross=await holdAcrossTabs([page,second],crossMarker);await ingest(crossMarker+'：资料备注已更新。');
   await page.locator('#toggleReceive').click();await cross.ready();await page.locator('#toggleReceive').click();await second.locator('#connectionStatus').filter({hasText:'已停止接收'}).waitFor();
   await cross.release();await sleep(350);
   for(const tab of [page,second])assert.ok(!(await tab.locator('#history').innerText()).includes(crossMarker),'another tab cannot display its delayed response after shared stop');
   for(const response of cross.held)assert.ok(!acknowledged.includes(response.event.id),'another tab cannot ACK its delayed response after shared stop');
   assert.equal((await stored(second)).enabled,false,'another tab cannot overwrite the persisted stop');
   await page.locator('#toggleReceive').click();await delivered(page,crossMarker,session);await second.locator('#history').filter({hasText:crossMarker}).waitFor();assert.equal(await page.locator('#history .event').count(),3,'resume shares one deduplicated reminder history across tabs');
   await layout(page);await page.screenshot({path:path.join(artifacts,'phone-reminders-browser-390.png'),fullPage:true});
   await page.locator('#toggleReceive').click();await second.locator('#connectionStatus').filter({hasText:'已停止接收'}).waitFor();
   const oldMarker=label+' 跨标签页旧配对消息',oldPair=await holdAcrossTabs([page,second],oldMarker);await ingest(oldMarker+'：旧连接在途材料。');await page.locator('#toggleReceive').click();await oldPair.ready();
   await page.locator('#disconnect').click();await page.locator('#pairForm').waitFor({state:'visible'});await second.locator('#pairForm').waitFor({state:'visible'});const disconnected=await stored(page);assert.equal(disconnected.session,null);assert.equal(disconnected.enabled,false);assert.equal(disconnected.history.length,3,'disconnect keeps local reminder history');
   const repaired=await pair(page,label+' 重新配对手机');assert.ok(repaired.device_id!==session.device_id,'re-pair receives a new independent device identity');
   await oldPair.release();await sleep(350);assert.equal((await stored(second)).session.device_id,repaired.device_id,'late response from another tab cannot restore the previous pairing');
   for(const tab of [page,second])assert.ok(!(await tab.locator('#history').innerText()).includes(oldMarker),'old pairing response cannot display after re-pair');for(const response of oldPair.held)assert.ok(!acknowledged.includes(response.event.id),'old pairing response cannot ACK after re-pair');
   await second.close();await api('/api/mobile-reminders/revoke',{id:repaired.device_id});await page.locator('#connectionStatus').filter({hasText:'配对已失效'}).waitFor();await page.locator('#pairForm').waitFor({state:'visible'});const revoked=await stored(page);assert.equal(revoked.session,null);assert.equal(revoked.enabled,false);assert.match(await page.locator('#notice').innerText(),/撤销|重新连接/);assert.equal(revoked.history.length,3,'revocation keeps local history');
  }
  assert.deepEqual(errors,[],label+' page has no uncaught frontend errors');
 }finally{if(heldRelease){await heldRelease();heldRelease=null;}await context.close();}
}
(async()=>{
 const env={...process.env};delete env.CI_ACCESS_TOKEN;
 server=spawn(python,[path.join(root,'server.py'),'--port','0','--reminder-port','0','--data-dir',directory],{cwd:root,windowsHide:true,env});
 mainUrl=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('isolated server startup timed out')),15000);server.stdout.on('data',chunk=>{output+=chunk.toString();const match=output.match(/ready: (http:\/\/127\.0\.0\.1:\d+)/);if(match){clearTimeout(timer);resolve(match[1]);}});server.on('error',error=>{clearTimeout(timer);reject(error);});server.on('exit',code=>{clearTimeout(timer);reject(Error('isolated server exited '+code));});});
 mainToken=fs.readFileSync(path.join(directory,'access-token.txt'),'utf8').trim();const status=await api('/api/mobile-reminders/settings',{enabled:true});assert.ok(status.enabled&&status.listening,'computer enables its real restricted listener');phoneUrl='http://127.0.0.1:'+status.port+'/';
 const rootResponse=await fetch(phoneUrl);assert.equal(rootResponse.status,200,'phone listener must serve its no-install page');
 browser=await playwright.chromium.launch({channel:'msedge',headless:true});await exercise(browser,'Edge',true);await browser.close();browser=null;
 let webkit;try{webkit=await playwright.webkit.launch({headless:true});}catch(error){if(!/Executable doesn't exist|browserType.launch:.*(not found|unsupported)|ENOENT/i.test(error.message))throw error;}
 if(webkit){browser=webkit;await exercise(browser,'WebKit',false);await browser.close();browser=null;console.log('PASS WebKit phone pairing, real delivery/ACK, persistence, escaping and 320/390px layout');}
 else console.log('SKIP WebKit: bundled browser executable is unavailable');
 console.log('PASS Edge phone browser: real isolated pairing/delivery/ACK, reload dedup, same-tab and cross-tab in-flight stop/re-pair fencing, resume, PC revoke, inert HTML, 320/390px and no installation requirement');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
 if(heldRelease){try{await heldRelease();}catch{}}
 if(browser)await browser.close();
 if(server&&server.exitCode===null){const stopped=new Promise(resolve=>server.once('exit',resolve));server.kill();await stopped;}
 const safe=path.resolve(directory);if(safe.startsWith(path.resolve(artifacts)+path.sep)&&path.basename(safe).startsWith('phone-reminders-browser-'))fs.rmSync(safe,{recursive:true,force:true});
});
