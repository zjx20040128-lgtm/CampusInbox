'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),os=require('os');
const {spawn}=require('child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temporaryRoot=path.join(root,'artifacts');
fs.mkdirSync(temporaryRoot,{recursive:true});
const directory=fs.mkdtempSync(path.join(temporaryRoot,'mobile-reminders-ui-'));
const python=process.env.CI_PYTHON||path.join(os.homedir(),'.cache','codex-runtimes','codex-primary-runtime','dependencies','python','python.exe');
let server,browser;
(async()=>{
 server=spawn(python,[path.join(root,'server.py'),'--port','0','--data-dir',directory],{cwd:root,windowsHide:true});
 const url=await new Promise((resolve,reject)=>{let stderr='';const timer=setTimeout(()=>reject(Error('server startup timed out: '+stderr)),15000);server.stderr.on('data',buffer=>stderr+=buffer);server.stdout.on('data',buffer=>{const m=buffer.toString().match(/ready: (http:\/\/127\.0\.0\.1:\d+)/);if(m){clearTimeout(timer);resolve(m[1])}});server.on('error',reject);server.on('exit',code=>{clearTimeout(timer);reject(Error('server exited '+code+': '+stderr))})});
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1366,height:900}});page.setDefaultTimeout(6000);
 const errors=[],calls=[];page.on('pageerror',error=>errors.push(error.message));
 let status={enabled:false,listening:false,port:8766,addresses:[],server_id:'test-pc',error:'',devices:[],android_version:'0.3.21'},failStatus=false,failSettings=false,holdNextStatus=false,releaseStatus,heldStatus;
 await page.route('**/api/mobile-reminders/**',async route=>{
  const request=route.request(),endpoint=new URL(request.url()).pathname.split('/').pop();calls.push({endpoint,method:request.method(),body:request.method()==='POST'?request.postDataJSON():undefined});
  if(endpoint==='status'){
   if(holdNextStatus){holdNextStatus=false;const snapshot=structuredClone(status);await new Promise(resolve=>{releaseStatus=async()=>{await route.fulfill({json:snapshot});resolve()};heldStatus()});return}
   await route.fulfill(failStatus?{status:503,json:{error:'状态暂时不可用'}}:{json:status});return;
  }
  if(endpoint==='settings'){
   if(failSettings){await route.fulfill({status:503,json:{error:'端口被占用'}});return}
   status={...status,enabled:request.postDataJSON().enabled,listening:request.postDataJSON().enabled,addresses:request.postDataJSON().enabled?['http://192.168.1.42:8766']:[]};await route.fulfill({json:status});return;
  }
  if(endpoint==='pairing'){assert.deepEqual(request.postDataJSON(),{});await route.fulfill({json:{code:'482106',expires_at:'2099-10-20T11:05:00+08:00'}});return}
  if(endpoint==='revoke'){assert.deepEqual(request.postDataJSON(),{id:'phone-a'});status.devices=status.devices.filter(device=>device.id!=='phone-a');await route.fulfill({json:{ok:true}});return}
  await route.fulfill({status:404,json:{error:'unexpected route'}});
 });
 await page.goto(url+'/#mobile');await page.locator('#wechatPush').waitFor();
 assert.equal(await page.locator('.browser-reminder-options').getAttribute('open'),null);
 await page.locator('.browser-reminder-options>summary').click();await page.locator('#mobileRemindersToggle').waitFor();
 assert.match(await page.locator('#mobileRemindersStatus').innerText(),/已关闭/);
 assert.ok(await page.locator('#mobileRemindersPair').isDisabled());
 assert.equal(await page.locator('#mobileReminders a[href$=".apk"]').count(),0,'phone browser flow does not require an APK');
 assert.match(await page.locator('#mobileReminders').innerText(),/手机浏览器/);
 assert.match(await page.locator('#mobileReminders').innerText(),/局域网页面需保持前台/);
 assert.match(await page.locator('#mobileReminders').innerText(),/HTTPS 后台通知入口/);
 assert.doesNotMatch(await page.locator('#mobileReminders').innerText(),/start-lan|配对令牌/);
 assert.equal(await page.locator('#mobileReminders input[type="password"]').count(),0);
 await page.locator('#mobileRemindersToggle').click();
 await page.locator('#mobileRemindersStatus').filter({hasText:'提醒已开启'}).waitFor();
 assert.match(await page.locator('#mobileRemindersAddresses').innerText(),/192\.168\.1\.42:8766/);
 assert.equal(await page.locator('#mobileRemindersAddresses a').getAttribute('href'),'http://192.168.1.42:8766/');
 assert.equal(await page.locator('[data-reminder-copy-address]').getAttribute('data-reminder-copy-address'),'http://192.168.1.42:8766/');
 await page.evaluate(()=>Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async value=>{window.copiedReminderAddress=value}}));
 await page.locator('[data-reminder-copy-address]').click();assert.equal(await page.evaluate(()=>window.copiedReminderAddress),'http://192.168.1.42:8766/');
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1),false,'phone browser access link fits narrow screens');
 await page.setViewportSize({width:1366,height:900});
 assert.ok(!(await page.locator('#mobileRemindersPair').isDisabled()));
 await page.locator('#mobileRemindersPair').click();await page.locator('#mobileRemindersCode').filter({hasText:'482106'}).waitFor();
 assert.match(await page.locator('#mobileRemindersExpiry').innerText(),/2099/);
 await page.getByText('更多连接选项',{exact:true}).click();await page.getByText('调整接收应用',{exact:true}).click();
 await page.locator('#packageList').fill('unsaved.package');
 status.devices=[{id:'phone-a',name:'<img src=x onerror="window.reminderXss=1">',paired_at:'2026-10-20T10:00:00+08:00',last_seen:'2026-10-20T11:00:00+08:00',online:true},{id:'phone-b',name:'离线手机',paired_at:'2026-10-19T10:00:00+08:00',last_seen:null,online:false}];
 await page.locator('#mobileRemindersDevices').getByText('离线手机',{exact:true}).waitFor({timeout:8000});
 assert.match(await page.locator('#mobileRemindersDevices').innerText(),/在线/);assert.match(await page.locator('#mobileRemindersDevices').innerText(),/离线/);
 assert.match(await page.locator('#mobileRemindersDevices').innerText(),/2026.10.20 11:00/);
 assert.equal(await page.locator('#mobileRemindersDevices img').count(),0);assert.equal(await page.evaluate(()=>window.reminderXss),undefined);
 assert.equal(await page.locator('#packageList').inputValue(),'unsaved.package');assert.equal(await page.locator('#mobileRemindersCode').innerText(),'482106');
 await page.locator('[data-reminder-revoke="phone-a"]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-reminder-revoke]').length===1);
 failStatus=true;await page.locator('#mobileRemindersError').filter({hasText:'状态暂时不可用'}).waitFor({timeout:8000});
 assert.equal(await page.locator('#mobileRemindersCode').innerText(),'482106');failStatus=false;
 await page.locator('#mobileRemindersError').waitFor({state:'hidden',timeout:8000});
 failSettings=true;await page.locator('#mobileRemindersToggle').click();await page.locator('#mobileRemindersError').filter({hasText:'端口被占用'}).waitFor();
 assert.ok(!(await page.locator('#mobileRemindersToggle').isDisabled()));failSettings=false;
 holdNextStatus=true;await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('status polling did not run')),8000);heldStatus=()=>{clearTimeout(timer);resolve()}});
 await page.locator('#mobileRemindersToggle').click();await page.locator('#mobileRemindersStatus').filter({hasText:'已关闭'}).waitFor();
 await releaseStatus();await page.waitForTimeout(200);assert.match(await page.locator('#mobileRemindersStatus').innerText(),/已关闭/,'a delayed pre-stop status must not reactivate the UI');
 assert.ok(await page.locator('#mobileRemindersPair').isDisabled());assert.equal(await page.locator('#mobileRemindersCode').innerText(),'尚未生成');
 const mutations=calls.filter(call=>call.method==='POST');
 assert.deepEqual(mutations.map(call=>[call.endpoint,call.body]),[['settings',{enabled:true}],['pairing',{}],['revoke',{id:'phone-a'}],['settings',{enabled:false}],['settings',{enabled:false}]]);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1),false);
 await page.screenshot({path:path.join(root,'artifacts','mobile-reminders-mobile.png'),fullPage:true});
 await page.locator('.sidebar [data-view="today"]').click();const count=calls.filter(call=>call.endpoint==='status').length;
 await page.waitForTimeout(5500);assert.equal(calls.filter(call=>call.endpoint==='status').length,count,'status polling stops after leaving mobile view');
 await page.locator('.sidebar [data-view="mobile"]').click();await page.locator('#mobileRemindersToggle').waitFor({state:'attached'});
 await page.locator('.sidebar [data-view="mobile"]').click();await page.locator('#mobileRemindersToggle').waitFor({state:'attached'});
 const before=calls.filter(call=>call.endpoint==='status').length;await page.waitForTimeout(5500);
 assert.equal(calls.filter(call=>call.endpoint==='status').length-before,1,'reentering the view leaves only one status timer');
 assert.deepEqual(errors,[]);
 console.log('PASS mobile reminders UI: phone browser address/copy without APK, enable/pair/device status/revoke/stop, failures, escaping, retained edits/code, scoped polling, 390px and no frontend errors');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
 if(browser)await browser.close();if(server&&server.exitCode===null){const stopped=new Promise(resolve=>server.once('exit',resolve));server.kill();await stopped;}
 const safe=path.resolve(directory);if(safe.startsWith(path.resolve(temporaryRoot)+path.sep)&&path.basename(safe).startsWith('mobile-reminders-ui-'))fs.rmSync(safe,{recursive:true,force:true});
});
