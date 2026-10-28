'use strict';
const {TaskCenterCollector}=require('./task-center.cjs');
const {assignmentContentUrl}=require('../browser-companion/tasks.js');
const MAX_FILE=32*1024*1024;
function allowedDownload(value){
 try{
  const u=new URL(value);
  return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&
   (u.hostname==='chaoxing.com'||u.hostname.endsWith('.chaoxing.com')||u.hostname==='cldisk.com'||u.hostname.endsWith('.cldisk.com'));
 }catch{return false}
}
async function downloadOriginal(context,job,file,readTask){
 if(job.kind!=='task_center'||!assignmentContentUrl(job))throw Error('unsupported');
 const object=file.url?.match(/^https:\/\/d0\.cldisk\.com\/download\/([a-fA-F0-9]{32})$/)?.[1];
 if(!object&&file.kind!=='inline_image')throw Error('file');
 // Revalidate the source using the current authorized task page, including download restrictions.
 const read=readTask||(()=>new TaskCenterCollector({context,accepted:new Set(),isCurrent:()=>true,onMessage:()=>{},onStatus:()=>{}}).detail(job));
 const current=await read();
 if(current.detail_state!=='read'||!current.attachments?.some(a=>a.name===file.name&&a.url===file.url))throw Error('restricted');
 const origin=new URL(job.url).origin;
 let target=object?origin+'/mooc-ans/ueditorupload/read?objectId='+object:file.url;
 const seen=new Set();
 for(let hop=0;hop<5;hop++){
  if(!allowedDownload(target)||seen.has(target))throw Error('redirect');seen.add(target);
  const response=await context.request.get(target,{maxRedirects:0,timeout:15000,headers:{Referer:origin+'/'}});
  try{
   if([301,302,303,307,308].includes(response.status())){target=new URL(response.headers().location||'',target).href;continue}
   if(response.status()!==200||Number(response.headers()['content-length'])>MAX_FILE||/^text\/html\b/i.test(response.headers()['content-type']||''))throw Error('download');
   const bytes=await response.body();
   if(!bytes.length||bytes.length>MAX_FILE)throw Error('size');
   if(/\.bmp$/i.test(file.name)&&(bytes.length<54||bytes.toString('ascii',0,2)!=='BM'||bytes.readUInt32LE(2)!==bytes.length))throw Error('bitmap');
   return bytes;
  }finally{await response.dispose()}
 }
 throw Error('redirect');
}
module.exports={downloadOriginal};
if(require.main===module){
 let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);process.stdin.on('end',async()=>{
  let browser;try{
   const {session,job,file}=JSON.parse(input);input='';
   const {chromium}=require('playwright');browser=await chromium.launch({channel:'msedge',headless:true});
   const context=await browser.newContext({storageState:session});
   const bytes=await downloadOriginal(context,job,file);
   process.stdout.write(JSON.stringify({content_base64:bytes.toString('base64')}));
  }catch{
   // Signed URLs and cookies must never be printed in errors.
   process.stdout.write(JSON.stringify({error:'附件下载失败，请确认学习通登录有效且原任务允许下载，然后重试。'}));process.exitCode=1;
  }finally{if(browser)await browser.close()}
 });
}
