'use strict';
const assert=require('node:assert/strict'),{chromium}=require('playwright'),{createHmac}=require('crypto');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const server=createTestServer('campusinbox-file-formats-');let browser;
(async()=>{
 const {url,token,api}=await server.start();
 const attachments=['image1.bmp','lena.raw','实验材料.zip','main.cpp'].map((name,i)=>({name,url:'https://d0.cldisk.com/download/'+String(i+1).padStart(32,'0'),status:'skipped',error:'原文件已关联，未自动提取文字。'}));
 await api('chaoxing/messages',{kind:'task_center',message_id:'files_ui',title:'图像增强',text:'请使用附件完成图像增强实验。',course:'数字图像处理',conversation:'一班',captured_at:'2026-10-25T10:00:00+08:00',task_type:'assignment',detail_state:'read',url:'https://mooc1.chaoxing.com/mooc2/work/detail?courseId=1&classId=2&workId=43',attachments},undefined,createHmac('sha256',token).update('courseinbox:chaoxing-web:v1').digest('hex'));
 const state=await api('state'),p=state.proposals[0];
 const confirmed=await api('proposals/'+p.id+'/confirm',{});const id=confirmed.task?.id||confirmed.id;
 assert.ok(id,'fixture must confirm one task');
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(5000);
 await page.goto(url+'/?task='+id+'#tasks');
 await page.locator('#taskAttachments').waitFor({state:'visible'});
 for(const a of attachments)assert.equal(await page.locator('#taskAttachments').getByText(a.name,{exact:true}).count(),1);
 assert.equal(await page.locator('#taskAttachments [data-attachment-download]').count(),4);assert.equal(await page.locator('#taskAttachments').getByText('原文件已关联',{exact:true}).count(),4);
 let signedRequests=0;
 await page.route('**/api/messages/*/attachments/0/download',async route=>{
  assert.equal(route.request().headers().authorization,'Bearer '+token);signedRequests++;
  await route.fulfill({status:200,contentType:'application/octet-stream',body:Buffer.from('BM-original-file')});
 });
 const downloaded=page.waitForEvent('download');await page.locator('#taskAttachments [data-attachment-download]').first().click();
 const download=await downloaded;assert.equal(download.suggestedFilename(),'image1.bmp');assert.equal(signedRequests,1);
 assert.equal(page.url().startsWith(url),true,'file downloads must not navigate into a blank/403 cloud page');
 await page.route('**/api/messages/*/attachments/1/download',route=>route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'附件下载失败，请重新登录。'})}));
 await page.locator('#taskAttachments [data-attachment-download]').nth(1).click();await page.getByText('附件下载失败，请重新登录。',{exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);
 console.log('PASS confirmed task file links for BMP/RAW/archive/source, original-file labels, 390px layout and no JS errors');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close();await server.close()});
