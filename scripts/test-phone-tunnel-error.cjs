'use strict';
const assert=require('node:assert/strict'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');const server=createTestServer('tunnel-error-');let browser;
(async()=>{
 const {api}=await server.start();await api('mobile-reminders/settings',{enabled:true});const status=await api('mobile-reminders/status');
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();await page.goto('http://127.0.0.1:'+status.port+'/');
 await page.route('**/v1/health',route=>route.fulfill({status:530,body:'error code: 1033'}));
 await page.locator('#pairCode').fill('123456');await page.locator('#connect').click();await page.locator('#notice').waitFor({state:'visible'});
 const message=await page.locator('#notice').innerText();assert.match(message,/HTTPS.*隧道/);assert.doesNotMatch(message,/同一.*Wi-Fi/);
 console.log('PASS public-tunnel 530 reports the failed HTTPS tunnel rather than Wi-Fi or pairing-code failure');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await server.close()}});
