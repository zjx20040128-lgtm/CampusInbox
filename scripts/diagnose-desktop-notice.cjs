/* Read-only account DOM probe. Session arrives over stdin; output contains counts only. */
'use strict';
const fs=require('fs'),path=require('path'),{chromium}=require('playwright');
async function run(session){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({storageState:session}),page=await context.newPage();
  await page.goto('https://i.chaoxing.com',{waitUntil:'domcontentloaded',timeout:20000});
  let frame;
  for(let i=0;i<40;i++){
   frame=page.frames().find(f=>{try{const u=new URL(f.url());return u.origin==='https://notice.chaoxing.com'&&u.pathname==='/pc/notice/myNotice'}catch{return false}});
   if(frame)break;
   const link=page.getByText('收件箱',{exact:true});if(await link.count())await link.first().click();
   await page.waitForTimeout(500);
  }
  if(!frame){console.log(JSON.stringify({list_found:false}));return}
  await frame.locator('.dataBody_item').first().waitFor({timeout:15000});
  for(const name of ['parser.js','notices.js'])await frame.evaluate(fs.readFileSync(path.join(__dirname,'../browser-companion',name),'utf8'));
  const rows=await frame.evaluate(()=>CourseInboxNotices.extractList(document,location.href));
  const accepted=new Set(JSON.parse(fs.readFileSync(path.join(__dirname,'../data/chaoxing-sync/accepted.json'),'utf8')));
  const pending=rows.filter(row=>!accepted.has('notice_'+new URL(row.url).pathname.split('/')[3].replace(/^\$[A-Z]+\$/,'')));
  console.log(JSON.stringify({list_found:true,rendered_notices:rows.length,pending_notices:pending.length}));if(!rows.length)return;
  const targets=(pending.length?pending:rows).slice(0,6).map((row,index)=>({mode:'canonical',index,url:row.url}));
  for(const target of targets){
   const detail=await context.newPage(),response=await detail.goto(target.url,{waitUntil:'domcontentloaded',timeout:20000});
   await detail.waitForTimeout(5000);
   const probe=await detail.evaluate(()=>{
    const c=document.querySelector('.noticeContent'),t=document.querySelector('#title');
    return {title_tag:t?.tagName||'',title_chars:t?.textContent?.trim().length||0,content_present:Boolean(c),content_tag:c?.tagName||'',content_html_chars:c?.innerHTML?.trim().length||0,content_text_chars:c?.textContent?.trim().length||0,content_visible_chars:c?.innerText?.trim().length||0,images:c?.querySelectorAll('img').length||0,attachments:c?.querySelectorAll('iframe.attach-insertCloud[name]').length||0,body_chars:document.body?.innerText?.length||0,iframe_count:document.querySelectorAll('iframe').length,unavailable:/通知不存在|通知已删除|无权查看|暂无权限/.test(document.body?.innerText||''),login_marker:Boolean(document.querySelector('#quickCode'))};
   });
   console.log(JSON.stringify({index:target.index,mode:target.mode,status:response?.status(),official_origin:new URL(detail.url()).origin==='https://notice.chaoxing.com',...probe}));await detail.close();
  }
 }finally{await browser.close()}
}
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>{let session;try{session=JSON.parse(input)}catch{console.error('Invalid session input');process.exitCode=1;return}input='';run(session).catch(e=>{console.error(e.name+': notice diagnostic failed');process.exitCode=1})});
