'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const testServer=createTestServer('courseinbox-sync-summary-');
const {root}=testServer;
const output=path.join(root,'artifacts/sync-summary');fs.mkdirSync(output,{recursive:true});
let browser;
(async()=>{
 const {url}=await testServer.start();
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page.setDefaultTimeout(5000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let status={enabled:true,state:'partial',session_saved:true,freshness:'fresh',last_checked:'2026-10-22T09:59:00+08:00',last_received:'2026-10-21T10:39:00+08:00',last_error:'部分详情、附件或图片尚未读取，请打开原文核对；已支持的内容会继续检查。',sources:{chat:{state:'partial',pending_count:8,media_pending_count:18,issue_summary:'第1个会话、第2个会话'},notice:{state:'partial',last_complete_success:'2026-10-22T09:00:00+08:00',media_pending_count:2,attachment_pending_count:3},task_center:{state:'partial',unsupported_detail_count:6,coverage:'list_only'}}};
 await page.route('**/api/chaoxing/desktop/status',r=>r.fulfill({json:status}));
 let action;for(const endpoint of ['resume','recheck'])await page.route('**/api/chaoxing/desktop/'+endpoint,r=>{action=endpoint;return r.fulfill({json:{}})});
 await page.goto(url+'/#sync');await page.getByRole('heading',{name:'部分消息待重试',exact:true}).waitFor();
 assert.match(await page.locator('#desktopLastComplete').innerText(),/09:00/);
 assert.equal(await page.locator('#desktopSources').isVisible(),false,'source diagnostics start collapsed');
 assert.equal(await page.locator('#desktopCounts').isVisible(),false,'receipt statistics start collapsed');
 assert.equal(await page.locator('#desktopError').isVisible(),false,'detailed errors belong in diagnostics');
 for(const selector of ['#desktopLogin','#desktopLogout','[data-download="acceptance"]'])assert.equal(await page.locator(selector).isVisible(),false,selector+' is a secondary operation');
 assert.equal(await page.locator('#desktopPause').isVisible(),true,'pause remains a main control');
 assert.equal(await page.locator('#desktopResume').isVisible(),true);
 assert.match(await page.locator('#desktopLatest').innerText(),/未读完整|核对/);
 assert((await page.locator('#desktopLatest').innerText()).length<65);
 await page.locator('#desktopResume').click();assert.equal(action,'resume');
 await page.locator('#desktopOptions>summary').click();
 for(const selector of ['#desktopLogin','#desktopLogout','[data-download="acceptance"]'])assert.equal(await page.locator(selector).isVisible(),true);
 await page.locator('#desktopDiagnostics>summary').click();await page.locator('#desktopSources').filter({hasText:'图片或媒体待核对 18'}).waitFor();
 assert.match(await page.locator('#desktopTimeline').innerText(),/最近检查.*最近收到/);
 await page.locator('#desktopRecheck').click();assert.equal(action,'recheck');
 // A polling refresh preserves expanded controls and diagnostics.
 await page.waitForResponse(r=>r.url().endsWith('/desktop/status'));
 assert.equal(await page.locator('#desktopOptions').getAttribute('open'),'');
 assert.equal(await page.locator('#desktopDiagnostics').getAttribute('open'),'');
 await page.locator('#desktopOptions>summary').click();
 for(const width of [1440,768,390,320]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);if(width===1440||width===390)await page.screenshot({path:path.join(output,'summary-'+width+'.png'),fullPage:true})}
 for(const [state,enabled,saved,primary] of [['connected',true,true,'desktopRecheck'],['paused',false,true,'desktopResume'],['expired',true,true,'desktopLogin'],['idle',false,false,'desktopLogin']]){
  status={enabled,session_saved:saved,state,sources:{},freshness:'fresh'};
  await page.goto(url+'/?state='+state+'#sync');await page.locator('#'+primary).waitFor({state:'visible'});
  assert.equal(await page.locator('.desktop-sync-panel>.toolbar .button.primary:visible').count(),1,state+' has one main action');
  assert.equal(await page.locator('#desktopOptions').getAttribute('open'),null);
 }
 assert.deepEqual(errors,[]);console.log('PASS sync summary: compact defaults, state-specific main action, retained diagnostics/actions, polling preserves expansion, 320/390/768/1440px');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{try{await browser?.close()}finally{await testServer.close()}});
