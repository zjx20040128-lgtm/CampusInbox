'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');const server=createTestServer('wechat-push-');let browser;
(async()=>{
 const {url,api}=await server.start();browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:390,height:844}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const unauth=await page.request.get(url+'/api/wechat-push/status');assert.equal(unauth.status(),401);
 await page.goto(url+'/#mobile');await page.locator('#wechatPushStatus').filter({hasText:'尚未配置'}).waitFor();
 assert(await page.locator('#wechatPushTest').isDisabled());assert.equal(await page.locator('#wechatPushToken').getAttribute('type'),'password');
 const secret='fixture-token-12345678901234567890';await page.locator('#wechatPushToken').fill(secret);await page.locator('#wechatPushEnabled').check();await page.locator('#wechatPushSave').click();await page.locator('#wechatPushStatus').filter({hasText:'已开启'}).waitFor();
 assert.equal(await page.locator('#wechatPushToken').inputValue(),'');assert(!JSON.stringify(await api('wechat-push/status')).includes(secret));assert(!fs.readFileSync(path.join(server.directory,'wechat-push-token.bin')).includes(Buffer.from(secret)));
 await page.route('**/api/wechat-push/test',route=>route.fulfill({json:{enabled:true,configured:true,last_result:'accepted',receipt:'fixture-receipt',recent:[]}}));
 await page.locator('#wechatPushTest').click();await page.locator('#wechatPushResult').filter({hasText:'微信送达尚未确认'}).waitFor();
 await page.locator('#wechatPushToken').fill('unsaved-change-123456789');await page.locator('#wechatPushTest').click();await page.locator('#wechatPushError').filter({hasText:'先保存设置'}).waitFor();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 await page.locator('#wechatPushToken').fill('');await page.locator('#wechatPushClear').click();await page.locator('#wechatPushStatus').filter({hasText:'尚未配置'}).waitFor();
 assert(!fs.existsSync(path.join(server.directory,'wechat-push-token.bin')));assert.deepEqual(errors,[]);
 console.log('PASS authenticated WeChat settings, encrypted/no-echo Token, explicit test action, accepted-vs-delivered wording, unsaved-field guard, clear and 390px');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await server.close()}});
