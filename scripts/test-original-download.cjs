'use strict';
const assert=require('node:assert/strict');
const {downloadOriginal}=require('../desktop-sync/original-file.cjs');
const id='a'.repeat(32),file={name:'image1.bmp',url:'https://d0.cldisk.com/download/'+id};
const job={kind:'task_center',title:'图像增强',url:'https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&classId=2&workId=43',task_type:'assignment'};
const bytes=Buffer.alloc(54);bytes.write('BM');bytes.writeUInt32LE(54,2);
const verified=async()=>({...job,detail_state:'read',attachments:[file]});
function context(mode='ok'){
 const calls=[];
 return {calls,request:{get:async(url,options)=>{
  calls.push(url);assert.equal(options.maxRedirects,0);assert.equal(options.headers.Referer,'https://mooc1.chaoxing.com/');
  const first=calls.length===1;
  return {status:()=>mode==='403'?403:first?302:200,headers:()=>first?{location:mode==='evil'?'http://127.0.0.1/private':mode==='loop'?url:'https://d0.cldisk.com/download/'+id+'?token=short-lived'}:{'content-type':mode==='html'?'text/html':'image/bmp'},body:async()=>mode==='bad-bmp'?Buffer.from('not a bitmap'):bytes,dispose:async()=>{}};
 }}};
}
(async()=>{
 let c=context();const result=await downloadOriginal(c,job,file,verified);
 assert.deepEqual(result,bytes);assert.equal(c.calls.length,2);
 assert.match(c.calls[0],/^https:\/\/mooc1\.chaoxing\.com\/mooc-ans\/ueditorupload\/read\?objectId=/,'use authenticated official entry rather than opening the unsigned cloud link');
 c=context();await assert.rejects(downloadOriginal(c,job,file,async()=>({...job,detail_state:'read',attachments:[]})));assert.equal(c.calls.length,0,'restricted/removed/foreign files cannot download');
 for(const mode of ['evil','loop','403','html','bad-bmp'])await assert.rejects(downloadOriginal(context(mode),job,file,verified),mode);
 c=context();await assert.rejects(downloadOriginal(c,{...job,task_type:'exam'},file,verified));assert.equal(c.calls.length,0);
 console.log('PASS official download entry, signed redirect, live file identity, restriction, bounded redirects, HTML/403 rejection and BMP bytes');
})().catch(e=>{console.error(e);process.exitCode=1});
