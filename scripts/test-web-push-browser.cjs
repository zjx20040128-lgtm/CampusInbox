'use strict';
const assert=require('node:assert/strict'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const server=createTestServer('web-push-');let browser;
(async()=>{
 const {api}=await server.start();await api('mobile-reminders/settings',{enabled:true});const status=await api('mobile-reminders/status');const origin='http://127.0.0.1:'+status.port;
 browser=await chromium.launch({channel:'msedge',headless:true});const context=await browser.newContext();await context.grantPermissions(['notifications'],{origin});
 await context.addInitScript(()=>{
  const encode=raw=>btoa(String.fromCharCode(...new Uint8Array(raw))).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
  PushManager.prototype.getSubscription=async()=>window.__testSubscription||null;
  PushManager.prototype.subscribe=async()=>{
   const keys=await crypto.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
   const data={endpoint:'https://fcm.googleapis.com/fcm/send/isolated-fixture',keys:{auth:encode(new Uint8Array(16)),p256dh:encode(await crypto.subtle.exportKey('raw',keys.publicKey))}};
   return window.__testSubscription={toJSON:()=>data,unsubscribe:async()=>{window.__testSubscription=null;return true}};
  };
 });
 const page=await context.newPage(),cdp=await context.newCDPSession(page);let registration;
 cdp.on('ServiceWorker.workerRegistrationUpdated',e=>{registration=e.registrations.find(r=>r.scopeURL===origin+'/')||registration});await cdp.send('ServiceWorker.enable');
 await page.goto(origin+'/');await page.locator('#pairCode').fill((await api('mobile-reminders/pairing',{})).code);await page.locator('#connect').click();await page.locator('#backgroundPush').waitFor({state:'visible'});await page.locator('#backgroundPush').click();await page.locator('#pushHint').filter({hasText:'后台提醒已开启'}).waitFor();
 assert.equal((await api('mobile-reminders/status')).web_push.subscriptions,1);
 await page.waitForTimeout(600);assert(registration,'actual service worker registration');
 // Chromium DevTools injects a push locally: no real provider or phone is claimed.
 const control=await context.newPage(),browserCDP=await context.newCDPSession(control);await browserCDP.send('ServiceWorker.enable');
 await page.close();
 await browserCDP.send('ServiceWorker.deliverPushMessage',{origin,registrationId:registration.registrationId,data:JSON.stringify({id:'closed-page-test',title:'关闭页面测试',body:'页面关闭后由服务工作线程显示'})});
 const inspect=await context.newPage();await inspect.goto(origin+'/');
 await inspect.waitForFunction(async()=>{const r=await navigator.serviceWorker.ready;return (await r.getNotifications()).some(n=>n.tag==='closed-page-test')});
 await api('mobile-reminders/revoke',{id:(await api('mobile-reminders/status')).devices[0].id});
 console.log('PASS paired subscription authorization, actual Service Worker registration and notification after page close; provider and Android delivery remain separate');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await server.close()}});
