/* Read-only visual check of every desktop page and common dialogs. */
'use strict';
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const tag=process.argv[2]||'after';
if(!/^[a-z-]+$/.test(tag))throw Error('Invalid check tag');
const directory=path.resolve(__dirname,'../artifacts/ui-review-20261023',tag);
fs.mkdirSync(directory,{recursive:true});
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage();const errors=[],writes=[],results=[];
    await page.emulateMedia({reducedMotion:'reduce'});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(['POST','PATCH','DELETE'].includes(r.method()))writes.push(r.url())});
    async function record(name){
      await page.screenshot({path:path.join(directory,name+'.png'),fullPage:true});
      const visible=await page.locator('#content').innerText();
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      assert(!overflow,name+' page overflow');results.push({name,characters:visible.length});
    }
    for(const width of [1280,390]){
      await page.setViewportSize({width,height:1000});
      for(const [view,ready] of [['today','.hero'],['tasks','#taskRows'],['inbox','#inboxBody'],['calendar','#calendarNow'],['sync','#taskInventorySummary'],['mobile','#wechatPushSave:not([disabled])'],['evaluation','#evaluationDatasetSummary']]){
        await page.goto('about:blank');
        await page.goto('http://127.0.0.1:8765/#'+view);
        await page.locator(ready).waitFor();
        if(view==='evaluation')await page.waitForFunction(()=>!document.querySelector('#evaluationDataset')?.textContent.includes('正在读取'));
        if(view==='sync')await page.waitForFunction(()=>!document.querySelector('#taskInventorySummary')?.textContent.includes('正在读取'));
        await record(view+'-'+width);
        if(view==='inbox'){
          for(const tab of ['conflicts','archived','messages']){
            await page.locator(`[data-inbox-tab="${tab}"]`).click();
            if(tab==='messages')await page.locator('.message-tools').waitFor();
            await record('inbox-'+tab+'-'+width);
          }
          const message=page.locator('[data-message-detail]').first();
          if(await message.count()){
            await message.click();await page.locator('#messageDetailText').waitFor();await page.locator('#messageDialog').screenshot({path:path.join(directory,'message-dialog-'+width+'.png')});
            const supplement=page.locator('#messageDialog [data-supplement]');
            if(await supplement.count()){await supplement.first().click();await page.locator('#supplementDialog').waitFor();await page.locator('#supplementDialog').screenshot({path:path.join(directory,'supplement-dialog-'+width+'.png')});await page.locator('#supplementDialog [data-close]').first().click()}
            else await page.locator('#messageDialog [data-close]').click();
          }
          const selection=page.locator('[data-message-select]').first();
          if(await selection.count()){await selection.check();await page.locator('#clearSelectedMessages').click();await page.locator('#cleanupDialog').screenshot({path:path.join(directory,'cleanup-dialog-'+width+'.png')});await page.locator('#cleanupCancel').click()}
        }
        if(view==='tasks'){
          const task=page.locator('#taskRows [data-detail]').first();
          if(await task.count()){await task.click();await page.locator('#detailStatus').waitFor();await page.locator('#taskDialog').screenshot({path:path.join(directory,'task-dialog-'+width+'.png')});await page.locator('#taskDialog [data-close]').click()}
        }
        if(view==='evaluation'){
          await page.locator('[data-eval-tab="labels"]').first().click();await page.locator('#evaluationEditor').waitFor();await record('evaluation-labels-'+width);
        }
      }
      for(const [button,dialog] of [['#importOpen','#importDialog'],['#assistantOpen','#assistantDialog']]){
        await page.locator(button).click();await page.locator(dialog).screenshot({path:path.join(directory,dialog.slice(1)+'-'+width+'.png')});await page.locator(dialog+' [data-close]').first().click();
      }
    }
    await page.goto('http://127.0.0.1:8766/');
    await page.locator('#pairForm').waitFor();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(directory,'phone-receiver-390.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
    fs.writeFileSync(path.join(directory,'result.json'),JSON.stringify({results,errors,writes},null,2));
    console.log('PASS: all seven pages, inbox tabs, evaluation labels and common dialogs at 1280/390px; no page errors, overflow or write requests.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
