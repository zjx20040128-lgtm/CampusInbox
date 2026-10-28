'use strict';
const assert=require('node:assert/strict'),{spawnSync}=require('child_process'),{chromium}=require('playwright');
const {createTestServer}=require('./lib/browser-test-server.cjs');
const server=createTestServer('campusinbox-hybrid-ui-');let browser;
(async()=>{
 const seed=spawnSync(server.python,['-B','-c',
  "import sys;from pathlib import Path;from courseinbox.core import Inbox,parse_message;b=Inbox(Path(sys.argv[1])/'inbox.sqlite3');text='实验一：请提交报告，截止2026年10月30日18:00。';c=parse_message(text,'2026-10-25T10:00:00+08:00','课程甲','一班')[0];c['model_review']=[dict(field='deadline',rule='2026-10-25',model='2026-10-30T18:00:00+08:00',evidence='<img src=x onerror=alert(1)>',resolution='needs_review')];b.ingest(text,captured_at='2026-10-25T10:00:00+08:00',course='课程甲',scope='一班',candidates=[c]);[b.ingest('请阅读第'+str(i)+'章。',course='课程乙',candidates=[]) for i in range(20)]",server.directory],{cwd:server.root,encoding:'utf8',windowsHide:true});
 assert.equal(seed.status,0,seed.stderr);
 const {url,api}=await server.start();
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();let errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'/#inbox');const review=page.locator('.model-review').first();await review.locator('summary').click();
 assert.match(await review.innerText(),/规则 2026.*模型 2026/s);assert.equal(await review.locator('img').count(),0);
 await page.locator('[data-view="evaluation"]').click();await page.locator('#evaluationOptions>summary').click();
 await page.locator('#evaluationHoldout').click();await page.locator('#evaluationDatasetSummary').filter({hasText:'开发集用于调参'}).waitFor();
 assert.equal(await page.locator('#evaluationSplit').inputValue(),'holdout');assert.equal(await page.locator('#evaluationRules').isDisabled(),true);
 const dataset=await page.locator('#evaluationDataset').inputValue();
 const labels=await api('evaluation/labels?dataset='+dataset);
 assert(labels.items.some(i=>i.split==='holdout'));assert(labels.items.every(i=>!i.reviewed));
 const pick=labels.items.find(i=>i.split==='holdout');
 await api('evaluation/labels',{dataset,key:pick.key,revision:labels.revision,reviewed:true,expected_tasks:[{title:'测试未识别任务',deadline:null,operation:'create'}]});
 await page.reload();await page.locator('#evaluationDataset').selectOption(dataset);await page.locator('#evaluationOptions>summary').click();
 await page.waitForFunction(()=>!document.querySelector('#evaluationRules').disabled);
 await page.locator('#evaluationRules').click();await page.locator('#evaluationJobTitle').filter({hasText:'评测完成'}).waitFor({state:'attached'});
 const job=await api('evaluation/runs');assert.equal(job.results[0].labeled,1);assert.equal(job.results[0].evaluation_split,'holdout');
 assert(job.results[0].cases[0].error_types.includes('missed_task'));assert.equal(job.results[0].cases[0].route,'rules');
 await page.locator('#evaluationCases table').waitFor({state:'attached'});assert.match(await page.locator('#evaluationCases').textContent(),/漏报/);
 assert.deepEqual(errors,[]);console.log('PASS conflict evidence escaped, holdout creation, labels remain unreviewed, only reviewed holdout evaluated');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{await browser?.close();await server.close()});
