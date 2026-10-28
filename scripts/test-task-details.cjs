'use strict';
const assert=require('node:assert/strict'),fs=require('fs');
const {chromium}=require('playwright');
const {TaskCenterCollector}=require('../desktop-sync/task-center.cjs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.setContent(`<main class="work-details"><h1 class="work-title">实验三</h1><div class="work-description">提交报告 PDF 和源码 ZIP。</div><p class="deadline">截止：2026-10-20 18:00</p><p class="submission-method">上传附件</p><p class="status">待批阅</p><a class="attachment" href="https://d0.cldisk.com/download/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">实验要求.docx</a></main>`);
  await page.addScriptTag({content:fs.readFileSync('browser-companion/tasks.js','utf8')});
  const base={kind:'task_center',message_id:'task_42_abc_list',url:'https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&classId=2&workId=42',title:'实验三',text:'实验三',description:'',course:'数据库',conversation:'一班',task_type:'assignment',deadline:null,submission_method:'',platform_status:'未提交',field_evidence:{title:'实验三'}};
  const result=await page.evaluate(job=>CourseInboxTasks.enrichDetail(document,job.url,job),base);
  assert.equal(result.deadline,'2026-10-20T18:00:00+08:00');
  assert.equal(result.submission_method,'上传附件');assert.equal(result.platform_status,'待批阅');
  assert.match(result.description,/报告 PDF/);assert.equal(result.detail_state,'read');
  assert.equal(result.attachments[0].name,'实验要求.docx');assert.notEqual(result.message_id,base.message_id);
  const wrong=await page.evaluate(job=>CourseInboxTasks.enrichDetail(document,job.url.replace('workId=42','workId=43'),job),base);
  assert.equal(wrong.detail_state,'unavailable');assert.equal(wrong.deadline,null);
  await page.setContent('<div class="work-details"><h1 class="work-title">实验三</h1><script>截止：2026-10-01 00:00</script><div hidden class="deadline">截止：2026-10-02 00:00</div></div>');
  const hidden=await page.evaluate(job=>CourseInboxTasks.enrichDetail(document,job.url,job),base);
  assert.equal(hidden.deadline,null,'hidden fields cannot supply deadlines');
  assert.equal(hidden.detail_state,'unavailable','a title-only shell is not a read task description');
  await page.setContent('<main class="work-details"><h1 class="work-title">实验三</h1><p class="work-description">具体要求见附件</p>'+Array.from({length:22},(_,i)=>`<a class="attachment" href="${i===0?'https://example.invalid/file.pdf':'https://d0.cldisk.com/download/'+i.toString(16).padStart(32,'0')}">说明${i}.pdf</a>`).join('')+'</main>');
  const limited=await page.evaluate(job=>CourseInboxTasks.enrichDetail(document,job.url,job),base);
  assert.equal(limited.media_pending_count,2,'unsupported and over-budget files cannot silently disappear');
  assert.equal(limited.attachments.length,20);
  const operation={...base,url:base.url.replace('/view?','/task?')+'&answerId=7'};
  await page.setContent(`<ul class="bottomList"><li data="${operation.url}"><h3 class="title">实验三</h3><a href="${base.url.replace('workId=42','workId=99')}">别的任务</a><a data-detail-url="${base.url}" href="${base.url}">查看说明</a></li></ul>`);
  const discovered=await page.evaluate(()=>CourseInboxTasks.extractDocument(document,'https://mooc1.chaoxing.com/mooc2/work/list',{course:'数据库',scope:'一班'}));
  assert.equal(new URL(discovered[0].detail_url).searchParams.get('workId'),'42','use only a same-identity read-only link actually supplied by the list');
  const {detailUrl}=require('../browser-companion/tasks.js');
  assert.equal(new URL(detailUrl({...operation,detail_url:base.url})).searchParams.get('workId'),'42');
  assert.equal(detailUrl({...operation,detail_url:base.url.replace('workId=42','workId=99')}),'');
  assert.equal(detailUrl({...base,url:base.url+'&answerId=7'}),'');
  const collector=new TaskCenterCollector({context:{newPage:()=>{throw Error('unsafe navigation')}},accepted:new Set(),isCurrent:()=>true,onMessage:()=>{},onStatus:()=>{}});
  assert.equal((await collector.detail({...base,task_type:'exam'})).detail_state,'skipped');
  assert.equal((await collector.detail({...base,url:base.url.replace('/view?','/task?')})).detail_state,'skipped');
  const liveContext=await browser.newContext();let writes=0,unsafeReads=0,redirect=false;
  await liveContext.route('**/*',route=>{
   const u=new URL(route.request().url());
   if(route.request().method()!=='GET'){writes++;return route.fulfill({body:'unexpected write'})}
   if(['/mooc-ans/work/task','/save','/submit'].includes(u.pathname))unsafeReads++;
   if(u.pathname==='/mooc2/work/list')return route.fulfill({contentType:'text/html',body:`<ul class="bottomList"><li data="${operation.url}"><h3 class="title">实验三</h3><span class="status">未提交</span><a href="${base.url}">只读说明</a></li></ul>`});
   if(u.pathname==='/mooc-ans/work/view')return redirect?route.fulfill({status:302,headers:{location:operation.url}}):route.fulfill({contentType:'text/html',body:'<main class="work-details"><h1 class="work-title">实验三</h1><p class="work-description">完成报告</p><p class="deadline">截止：2026-10-20 18:00</p></main><img src="/save"><script>fetch("/submit",{method:"POST"});fetch("/save")</script>'});
   return route.fulfill({body:''});
  });
  const tab=await liveContext.newPage();await tab.setContent('<ul><li>作业</li></ul><iframe src="https://mooc1.chaoxing.com/mooc2/work/list"></iframe>');
  const emitted=[],ids=new Set();const actual=new TaskCenterCollector({context:liveContext,accepted:ids,isCurrent:()=>true,onStatus:()=>{},onMessage:job=>{emitted.push(job);ids.add(job.message_id)}});
  await actual.list(tab,'assignment','数据库',{courseId:'1',classId:'2'});
  await actual.list(tab,'assignment','数据库',{courseId:'1',classId:'2'});
  assert.equal(emitted.length,2,'accepted jobs must still refresh platform checks');
  assert.equal(emitted[0].detail_state,'read');assert.equal(emitted[0].message_id,emitted[1].message_id,'stable details replay without duplicating source');
  assert.equal(emitted[0].url,discovered[0].url,'original source remains the operation link');
  redirect=true;assert.equal((await actual.detail(emitted[0])).detail_state,'unavailable','redirect into operation pages is blocked');
  assert.equal(writes,0,'read-only detail page cannot make writes');assert.equal(unsafeReads,0,'no operation navigation or background save GET is allowed');await liveContext.close();
  console.log('PASS task detail evidence, identity and safe navigation');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
