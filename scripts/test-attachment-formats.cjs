'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),vm=require('vm');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const parser=fs.readFileSync(path.join(root,'browser-companion/tasks.js'),'utf8');
const job={kind:'task_center',message_id:'format_fixture',title:'图像增强',text:'图像增强',course:'数字图像处理',conversation:'一班',task_type:'assignment',url:'https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&classId=2&workId=42',field_evidence:{title:'图像增强'}};
const id=n=>n.toString(16).padStart(32,'0');
const encoded=value=>Buffer.from(encodeURIComponent(JSON.stringify(value))).toString('base64');
const html=body=>`<main class="fanyaMarking"><div class="detailsHead"><h2 class="mark_title">图像增强</h2></div><div class="mark_table"><h3 class="mark_name">请使用附件完成实验。${body}</h3><div class="stem_answer"><div class="attachNew"><span data="${id(99)}" name="私人答案.zip">私人答案.zip</span></div></div></div></main>`;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();await page.route('**/*',r=>r.abort());
  const parse=async body=>{await page.setContent(html(body));await page.evaluate(parser);return page.evaluate(j=>CourseInboxTasks.enrichAssignment(document,j.url,j),job)};
  let result=await parse(`<p class="attachNew"><span data="${id(1)}" name="image1.BMP">image1.BMP</span></p><iframe class="attach-iframe" name="${encoded({objectid:id(2),name:'lena.bmp',type:'bmp',size:512})}"></iframe>`);
  assert.deepEqual(result.attachments.map(a=>a.name),['image1.BMP','lena.bmp'],'both official object metadata structures must retain original BMP files');
  assert.equal(result.attachments[1].url,'https://d0.cldisk.com/download/'+id(2));assert.equal(result.media_pending_count,0);
  const names=['data.raw','资料.zip','data.rar','data.7z','main.cpp','main.c','main.py','histogram.m','data.csv','report.xlsx','slides.pptx','old.doc','new-format.xyz'];
  result=await parse(names.map((name,i)=>`<p class="attachNew"><span data="${id(i+10)}" name="${name}">${name}</span></p>`).join(''));
  assert.deepEqual(result.attachments.map(a=>a.name),names,'file discovery must not depend on a text extraction suffix allowlist');
  result=await parse(`<p class="attachNew"><span data="${id(1)}" name="image1.bmp">image1.bmp</span></p><a class="attachment" href="https://d0.cldisk.com/download/${id(1)}">image1.bmp</a><iframe class="attach-iframe" name="malformed"></iframe><p class="attachNew"><span data="../../private" name="bad.zip">bad.zip</span></p>`);
  assert.equal(result.attachments.length,1);assert.equal(result.media_pending_count,2,'invalid metadata stays visibly incomplete');
  result=await parse(`<input id="allowDownloadAttachment" value="0"><script>window.ATTACH__NO_DOWNLOAD_PATH='/restricted';</script><p class="attachNew"><span data="${id(1)}" name="restricted.bmp">restricted.bmp</span></p>`);
  assert.equal(result.attachments.length,0,'download restrictions must not be bypassed');assert.ok(result.media_pending_count>0);
  const line={on(){return this}};
  const sandbox={__dirname:path.join(root,'desktop-sync'),require:name=>name==='playwright'?{chromium:{}}:name==='readline'?{createInterface:()=>line}:require(name.startsWith('./')?path.join(root,'desktop-sync',name):name),process:{argv:['node','worker',path.join(root,'artifacts')],stdin:{},stdout:{write(){}},on(){}},Buffer,URL,setTimeout,clearTimeout};
  vm.createContext(sandbox);vm.runInContext(fs.readFileSync(path.join(root,'desktop-sync/worker.cjs'),'utf8'),sandbox);
  sandbox.job={kind:'task_center',attachments:[{name:'image1.bmp',url:'https://d0.cldisk.com/download/'+id(1)},{name:'data.zip',url:'https://d0.cldisk.com/download/'+id(2)}]};
  const prepared=await vm.runInContext('active=true;prepare(job)',sandbox);
  assert.ok(prepared.attachments.every(a=>a.url&&a.status==='skipped'&&a.error.includes('原文件')),'binary assets retain links without pretending OCR text is available');
  console.log('PASS BMP structures, arbitrary suffix discovery, deduplication, answer exclusion, malformed/restricted metadata and original-file semantics');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
