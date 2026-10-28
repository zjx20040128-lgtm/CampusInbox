/* Read the signed-in student's visible course, assignment and exam lists. */
'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const PORTAL='https://i.chaoxing.com';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const official=value=>{try{const u=new URL(value);return u.protocol==='https:'&&(u.hostname==='chaoxing.com'||u.hostname.endsWith('.chaoxing.com'))}catch{return false}};
const identity=value=>{try{const u=new URL(value);const values=new Map([...u.searchParams].map(([key,id])=>[key.toLowerCase().replace(/[_-]/g,''),id.trim()]));return {courseId:values.get('courseid')||'',classId:values.get('classid')||values.get('clazzid')||''}}catch{return {courseId:'',classId:''}}};
const hasIdentity=value=>Boolean(value?.courseId&&value?.classId);
const failure=code=>Object.assign(Error(code),{code});
const {detailUrl,sameTask,assignmentContentUrl}=require('../browser-companion/tasks.js');
const {parseTime}=require('../browser-companion/parser.js');
const canonical=value=>/^\d+$/.test(value||'')?BigInt(value).toString():value;
function taskKey(job){
 try{const u=new URL(job.url),p=new Map([...u.searchParams].map(([k,v])=>[k.toLowerCase().replace(/[_-]/g,''),v]));const kind=job.task_type==='exam'?'exam':'assignment';const ids=[p.get('courseid'),p.get('classid')||p.get('clazzid'),kind==='exam'?(p.get('examid')||p.get('id')):(p.get('workid')||p.get('id'))];return ids.every(v=>/^[A-Za-z0-9_-]{1,80}$/.test(v||''))?[canonical(ids[0]),canonical(ids[1]),kind,canonical(ids[2])].join('|'):''}catch{return ''}
}

class TaskCenterCollector{
 constructor({context,accepted,isCurrent,onMessage,onStatus,onInventory=()=>{},cursor=0,detailCursors=[]}){
  Object.assign(this,{context,accepted,isCurrent,onMessage,onStatus,onInventory});this.repairs=new Set();this.sectionRepairs=new Set();this.checkinCache=new Map();
  this.cursor=Number.isSafeInteger(cursor)&&cursor>=0?cursor:0;
  this.page=null;this.lastTotal=0;this.issues=new Map();this.detailCursors=new Map();this.coverageIssues=new Map();this.visitedCourses=new Set();this.detailCache=new Map();this.mediaReceipts=new Set();
  for(const entry of (Array.isArray(detailCursors)?detailCursors:[]).slice(0,1000))if(Array.isArray(entry)&&/^[A-Za-z0-9_-]{1,80}:[A-Za-z0-9_-]{1,80}:(assignment|exam)$/.test(entry[0])&&Number.isSafeInteger(entry[1])&&entry[1]>=0)this.detailCursors.set(entry[0],entry[1]);
 }
 recordReceipt(id,complete){
  if(typeof id!=='string')return;
  if(complete===true)this.mediaReceipts.add(id);else this.mediaReceipts.delete(id);
  while(this.mediaReceipts.size>5000)this.mediaReceipts.delete(this.mediaReceipts.values().next().value);
 }
 requestRepair(keys){
  for(const key of Array.isArray(keys)?keys.slice(0,50):[])if(typeof key==='string'&&/^[A-Za-z0-9_-]{1,80}\|[A-Za-z0-9_-]{1,80}\|(assignment|exam)\|[A-Za-z0-9_-]{1,80}$/.test(key)&&this.repairs.size<100)this.repairs.add(key);
 }
 requestRepairSections(keys){
  for(const key of Array.isArray(keys)?keys.slice(0,50):[])if(typeof key==='string'&&/^[A-Za-z0-9_-]{1,80}\|[A-Za-z0-9_-]{1,80}\|(assignment|exam)$/.test(key)&&this.sectionRepairs.size<200)this.sectionRepairs.add(key);
 }
 report(state,counts={},stage='',reason=''){
  if(this.isCurrent())this.onStatus({state,error:state==='expired'?'expired':state==='partial'||state==='retrying'?'task_center':'',stage,reason,cursor:this.cursor,detail_cursors:[...this.detailCursors],...counts});
 }
 async detail(job){
  const url=detailUrl(job);
  if(!url&&assignmentContentUrl(job))return this.assignmentContent(job);
  if(!url)return {...job,detail_state:'skipped',detail_error:'此入口未验证为只读说明页，请打开原任务核对要求。'};
  let page;
  try{
   page=await this.context.newPage();
   const protocol=await this.context.newCDPSession(page);
   await protocol.send('Emulation.setScriptExecutionDisabled',{value:true});
   // Never follow a redirect into an answer/start page, nor submit a form.
   await page.route('**/*',route=>{const req=route.request();if(!['GET','HEAD'].includes(req.method())||!req.isNavigationRequest()||!detailUrl({...job,detail_url:'',url:req.url()})||!sameTask(job.url,req.url()))return route.abort();return route.fallback()});
   const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:12000});
   if(response?.status()>=400)throw Error('http');
   await page.locator('.work-details,.workDetail,.work-detail,[data-work-detail]').first().waitFor({timeout:3000});
   await page.evaluate(fs.readFileSync(path.join(__dirname,'../browser-companion/tasks.js'),'utf8'));
   const result=await page.evaluate(job=>CourseInboxTasks.enrichDetail(document,location.href,job),job);
   result._media_count=await page.locator(':is(.work-details,.workDetail,.work-detail,[data-work-detail]) :is(img,video,audio,canvas,object,embed,iframe)').count();
   if(result.detail_state!=='read'&&assignmentContentUrl(job))return await this.assignmentContent(job);
   return result;
  }catch{
   if(this.isCurrent()&&assignmentContentUrl(job))return await this.assignmentContent(job);
   return {...job,detail_state:'unavailable',detail_error:'作业详情未读取成功，保留列表信息，下轮重试。'};
  }
  finally{if(page)await page.close().catch(()=>{})}
 }
 async assignmentContent(job){
  let page;
  try{
   if(!this.context.request)return {...job,detail_state:'skipped',detail_error:'此环境不支持作业静态正文读取。'};
   let url=assignmentContentUrl(job),html='',finalUrl='';const visited=new Set();
   for(let hop=0;hop<4;hop++){
    if(!this.isCurrent()||!url||visited.has(url))throw Error('cancelled');visited.add(url);
    const response=await this.context.request.get(url,{maxRedirects:0,timeout:12000});
    try{
     const status=response.status();
     if([301,302,303,307,308].includes(status)){
      const target=new URL(response.headers().location||'',url).href;
      url=sameTask(job.url,target)?assignmentContentUrl({...job,url:target}):'';continue;
     }
     if(status!==200||!/^text\/html\b/i.test(response.headers()['content-type']||''))throw Error('html');
     const bytes=await response.body();if(bytes.length>4*1024*1024)throw Error('large');
     html=bytes.toString('utf8');finalUrl=url;break;
    }finally{await response.dispose()}
   }
   if(!finalUrl||!this.isCurrent())throw Error('redirect');
   page=await this.context.newPage();const protocol=await this.context.newCDPSession(page);
   await protocol.send('Emulation.setScriptExecutionDisabled',{value:true});
   await page.route('**/*',route=>route.abort());
   await page.setContent(html,{waitUntil:'domcontentloaded',timeout:5000});
   await page.evaluate(fs.readFileSync(path.join(__dirname,'../browser-companion/tasks.js'),'utf8'));
   return await page.evaluate(({url,job})=>CourseInboxTasks.enrichAssignment(document,url,job),{url:finalUrl,job});
  }catch{return {...job,detail_state:'unavailable',detail_error:'作业静态正文未读取成功，保留列表信息，下轮重试。'}}
  finally{if(page)await page.close().catch(()=>{})}
 }
 async checkinActivities(tab,course,expectedIdentity){
  let frame;for(let i=0;i<20&&this.isCurrent();i++){frame=tab.frames().find(f=>{try{const u=new URL(f.url());return u.protocol==='https:'&&u.hostname==='mobilelearn.chaoxing.com'&&u.pathname==='/page/active/stuActiveList'}catch{return false}});if(frame)break;await sleep(250)}
  if(!frame||!this.context.request)return {checked:0,captured:0};
  const actual=identity(frame.url());
  if(!hasIdentity(actual)||canonical(actual.courseId)!==canonical(expectedIdentity.courseId)||canonical(actual.classId)!==canonical(expectedIdentity.classId))return {checked:0,captured:0};
  await frame.waitForFunction(()=>Boolean(document.querySelector('li[activeid]'))||/暂无活动|没有活动|暂无数据/.test(document.body.innerText),null,{timeout:5000}).catch(()=>{});
  const rows=await frame.evaluate(()=>[...document.querySelectorAll('li[activeid]')]
   .filter(n=>n.querySelector('.icon-signin-g')&&/签到/.test(n.querySelector('.right-content')?.innerText||''))
   .slice(0,30).map(n=>({activity_id:n.getAttribute('activeid')||'',endedEvidence:[...n.querySelectorAll('*')].filter(x=>x.getClientRects().length&&getComputedStyle(x).visibility!=='hidden').map(x=>(x.textContent||'').trim()).find(x=>['已结束','已截止','已过教师设置的截止时间'].includes(x))||'',title:(n.querySelector('.right-content .overHidden2')?.textContent||n.querySelector('.right-content')?.textContent||'').trim().slice(0,160)}))).catch(()=>[]);
  let checked=0,captured=0;
  for(const row of rows){
   if(!this.isCurrent())break;
   const activityId=String(row.activity_id||'').trim(),title=String(row.title||'').trim();
   if(!/^[A-Za-z0-9_-]{1,80}$/.test(activityId)||!title||!title.includes('签到'))continue;
   checked++;
   let data=this.checkinCache.get(activityId)?.data;
   if(!data||Date.now()-this.checkinCache.get(activityId).at>30000){
    try{
     const url=new URL('https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo');url.searchParams.set('activeId',activityId);
     const response=await this.context.request.get(url.href,{timeout:10000,maxRedirects:0});
     if(response.status()!==200){await response.dispose();continue}
     const result=await response.json().catch(()=>null);await response.dispose();
     if(result?.result!==1||!result.data||typeof result.data!=='object')continue;
     data=result.data;this.checkinCache.set(activityId,{data,at:Date.now()});
     while(this.checkinCache.size>5000)this.checkinCache.delete(this.checkinCache.keys().next().value);
    }catch{continue}
   }
   const stamp=value=>{if(typeof value==='number'||/^\d{10,13}$/.test(String(value||''))){let n=Number(value);if(n<1e12)n*=1000;return Number.isSafeInteger(n)&&n>0?n:null}const n=Date.parse(String(value||''));return Number.isFinite(n)?n:null};
   const createdAt=stamp(data.createtime),endAt=stamp(data.endTime??data.endtime);
   const platformTitle=String(data.title||'').trim().replace(/\s+/g,' ').normalize('NFKC');
   const endedEvidence=['已结束','已截止','已过教师设置的截止时间'].includes(row.endedEvidence)?row.endedEvidence:'';
   if(!createdAt||(!endAt&&!endedEvidence)||(endAt&&endAt<=createdAt)||(platformTitle&&platformTitle!==title.replace(/\s+/g,' ').normalize('NFKC')))continue;
   const publishedAt=new Date(createdAt).toISOString(),deadline=endAt?new Date(endAt).toISOString():null;
   const messageId=`checkin_${activityId}_${endAt||'unknown'}${endedEvidence?'_ended':''}`;
   if(this.accepted.has(messageId))continue;
   const evidenceTime=endAt?String(data.endtimeStr||new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(endAt))):'';
   const job={kind:'checkin_activity',message_id:messageId,text:title,title,course:'',conversation:course,sender:'',display_time:'',captured_at:publishedAt,published_at:publishedAt,direction:'received',activity_id:activityId,course_id:canonical(expectedIdentity.courseId),class_id:canonical(expectedIdentity.classId),deadline,field_evidence:{deadline:'学习通签到活动结束时间：'+evidenceTime,published_at:'学习通活动创建时间：'+String(data.createtimeStr||publishedAt)}};
   if(!endAt)delete job.field_evidence.deadline;
   if(endedEvidence){job.activity_state='ended';job.field_evidence.activity_state=endedEvidence}
   try{await this.onMessage(job);captured++}catch{}
  }
  return {checked,captured};
 }
 async portal(){
  if(!this.page||this.page.isClosed())this.page=await this.context.newPage();
  const response=await this.page.goto(PORTAL,{waitUntil:'domcontentloaded',timeout:20000});
  if(response?.status()>=400)throw failure(response.status()>=500?'http_5xx':'http_error');
  for(let i=0;i<50&&this.isCurrent();i++){
   if(this.page.frames().some(f=>{try{const u=new URL(f.url());return u.hostname==='passport2.chaoxing.com'&&u.pathname.startsWith('/login')}catch{return false}}))throw failure('expired');
   const frame=this.page.frames().find(f=>{try{const u=new URL(f.url());return u.origin==='https://mooc2-ans.chaoxing.com'&&u.pathname==='/visit/interaction'}catch{return false}});
   if(frame&&await frame.locator('a.color1').count())return frame;
   await sleep(300);
  }
  throw failure('dom');
 }
 async list(tab,kind,course,expectedIdentity){
  if(!hasIdentity(expectedIdentity))throw failure('dom');
  const nav=tab.locator('li').filter({hasText:kind==='exam'?'考试':'作业'}).first();
  if(!await nav.count())throw failure('dom');
  await nav.click({timeout:5000});
  let frame;
  for(let i=0;i<50&&this.isCurrent();i++){
   frame=tab.frames().find(f=>{try{const u=new URL(f.url());return official(u.href)&&u.hostname==='mooc1.chaoxing.com'&&(kind==='exam'?u.pathname==='/exam-ans/mooc2/exam/exam-list':u.pathname==='/mooc2/work/list')}catch{return false}});
   if(frame)break;
   await sleep(300);
  }
  if(!frame)throw failure('dom');
  await frame.waitForFunction(()=>Boolean(document.querySelector('.bottomList li[data],.null-data,.exam-list li,.task-list li')),null,{timeout:15000}).catch(()=>{throw failure('timeout')});
  await frame.evaluate(fs.readFileSync(path.join(__dirname,'../browser-companion/tasks.js'),'utf8'));
  const jobs=await frame.evaluate(({course,kind})=>CourseInboxTasks.extractDocument(document,location.href,{course,scope:course,taskType:kind==='exam'?'exam':'assignment'}),{course,kind});
  const accepted=jobs.filter(job=>{const actual=identity(job.url);return hasIdentity(actual)&&actual.courseId===expectedIdentity.courseId&&actual.classId===expectedIdentity.classId});
  const rejected=jobs.length-accepted.length+accepted.filter(job=>!taskKey(job)).length;
  const count=await frame.locator('.bottomList li[data],.exam-list li,.task-list li').count();
  if(count>jobs.length)throw failure('dom');
  const manifest={phase:'section',course_id:expectedIdentity.courseId,class_id:expectedIdentity.classId,kind};
  this.onInventory({...manifest,jobs,complete:false,preliminary:true});
  const emitted=[];
  let captured=0,detailPending=0,unsupported=0,mediaPending=0;
  const detailKey=expectedIdentity.courseId+':'+expectedIdentity.classId+':'+kind;
  const readable=accepted.flatMap((job,index)=>(detailUrl(job)||assignmentContentUrl(job))?[index]:[]);
  const start=(this.detailCursors.get(detailKey)||0)%Math.max(1,readable.length);
  const priority=readable.filter(index=>this.repairs.has(taskKey(accepted[index])));
  const selected=new Set([...new Set([...priority,...Array.from({length:readable.length},(_,n)=>readable[(start+n)%readable.length])])].slice(0,5));
  this.detailCursors.set(detailKey,(start+selected.size)%Math.max(1,readable.length));
  const order=[...accepted.keys()].sort((a,b)=>Number(this.repairs.has(taskKey(accepted[b])))-Number(this.repairs.has(taskKey(accepted[a]))));
  for(const index of order){
   if(!this.isCurrent())break;
   const original=accepted[index];
   const readableUrl=detailUrl(original)||assignmentContentUrl(original);
   const cached=this.detailCache.get(original.message_id);
   const job=selected.has(index)?await this.detail(original):cached&&Date.now()-cached.at<600000?{...cached.job}:{...original,detail_state:'skipped',detail_error:readableUrl?'本轮详情预算已用完，后续轮次继续检查。':'此入口未验证为只读说明页，请打开原任务核对要求。'};
   if(!this.isCurrent())break;
   if(selected.has(index)){
    if(job.detail_state==='read')this.detailCache.set(original.message_id,{job:{...job},at:Date.now()});
    else this.detailCache.delete(original.message_id);
    while(this.detailCache.size>5000)this.detailCache.delete(this.detailCache.keys().next().value);
   }
   if(!readableUrl)unsupported++;
   else if(job.detail_state!=='read')detailPending++;
   job.media_pending_count=Math.min(1000,(Number.isSafeInteger(job._media_count)?job._media_count:0)+(Number.isSafeInteger(job.media_pending_count)?job.media_pending_count:0));
   mediaPending+=job.media_pending_count+(this.mediaReceipts.has(job.message_id)?0:(job.attachments?.length||0));delete job._media_count;
   // Replays refresh observed platform state; the server deduplicates raw evidence.
   await this.onMessage(job);if(!this.accepted.has(job.message_id))captured++;
   emitted.push(job);this.repairs.delete(taskKey(original));
   this.report('syncing',{checked_count:index+1,captured_count:captured},'task_list');
  }
  if(this.isCurrent())this.onInventory({...manifest,jobs:[...emitted,...jobs.filter(job=>!accepted.includes(job))],complete:emitted.length===accepted.length&&rejected===0,preliminary:false});
  return {checked:jobs.length,captured,rejected,detail_pending:detailPending,unsupported,media_pending:mediaPending};
 }
 async sweep(){
  if(!this.isCurrent())return;
  this.report(this.issues.size?'partial':'syncing',{},'task_navigation');
  let checked=0,captured=0,failed=0,reason='',processed=0;
  try{
   const frame=await this.portal();
   const rawTotal=await frame.locator('a.color1').count(),total=Math.min(rawTotal,100);
   if(!total)throw failure('dom');
   const courses=[];
   for(let i=0;i<total;i++){
    const link=frame.locator('a.color1').nth(i),ids=identity(new URL(await link.getAttribute('href')||'',frame.url()).href);
    courses.push({course_id:canonical(ids.courseId),class_id:canonical(ids.classId),course:(await link.textContent()||'').trim().slice(0,100),course_index:i+1});
   }
   this.onInventory({phase:'catalog',courses,truncated:rawTotal>total});
   if(!this.lastTotal){this.lastTotal=total;this.cursor%=total}
   else if(this.lastTotal!==total){this.cursor=0;this.issues.clear();this.coverageIssues.clear();this.visitedCourses.clear();this.lastTotal=total}
   const priorityIndex=courses.findIndex(course=>[...this.repairs,...this.sectionRepairs].some(key=>key.startsWith(course.course_id+'|'+course.class_id+'|')));
   const indexes=priorityIndex<0?[]:[priorityIndex];
   while(indexes.length<Math.min(3,total)){const index=this.cursor%total;this.cursor=(index+1)%total;if(!indexes.includes(index))indexes.push(index)}
   for(const index of indexes){
    if(!this.isCurrent())break;
    const courseLink=frame.locator('a.color1').nth(index);
    const course=await courseLink.textContent().then(s=>s.trim().slice(0,100));
    const linkIdentity=identity(new URL(await courseLink.getAttribute('href')||'',frame.url()).href);
    processed++;
    this.report('syncing',{checked_count:checked,captured_count:captured,pending_count:total-this.visitedCourses.size},'task_navigation');
    let tab;
    try{
     const before=this.context.pages();
     await frame.locator('a.color1').nth(index).click({timeout:8000});
     for(let i=0;i<20&&!tab&&this.isCurrent();i++){
      tab=this.context.pages().find(p=>!before.includes(p)&&official(p.url()));
      if(!tab)await sleep(250);
     }
     if(!tab)throw failure('dom');
     await tab.locator('li').filter({hasText:'作业'}).first().waitFor({timeout:20000});
     const pageIdentity=identity(tab.url());
     if((pageIdentity.courseId&&linkIdentity.courseId&&pageIdentity.courseId!==linkIdentity.courseId)||(pageIdentity.classId&&linkIdentity.classId&&pageIdentity.classId!==linkIdentity.classId))throw failure('dom');
     const expectedIdentity={courseId:pageIdentity.courseId||linkIdentity.courseId,classId:pageIdentity.classId||linkIdentity.classId};
     if(!hasIdentity(expectedIdentity))throw failure('dom');
     this.issues.delete('course:'+index);
     try{const activity=await this.checkinActivities(tab,course,expectedIdentity);checked+=activity.checked;captured+=activity.captured}catch{}
     for(const kind of ['assignment','exam']){
      if(!this.isCurrent())break;
      try{
       let result;
       for(let attempt=0;attempt<2;attempt++){
        try{result=await this.list(tab,kind,course,expectedIdentity);break}
        catch(error){if(attempt||!this.isCurrent()||!['dom','timeout'].includes(error.code))throw error;await sleep(1000)}
       }
       checked+=result.checked;captured+=result.captured;
       this.sectionRepairs.delete(canonical(expectedIdentity.courseId)+'|'+canonical(expectedIdentity.classId)+'|'+kind);
       this.coverageIssues.set(kind+':'+index,{detail_pending:result.detail_pending||0,unsupported:result.unsupported||0,media_pending:result.media_pending||0});
       if(result.rejected){failed++;reason='dom';this.issues.set(kind+':'+index,{course_index:index+1,section:kind})}
       else{
        this.issues.delete(kind+':'+index);
        // Existing jobs have all been emitted by list() before this checkpoint.
        if(result.rejected===0){
         const inventoryKey=crypto.createHash('sha256').update(`${expectedIdentity.courseId}|${expectedIdentity.classId}|${kind}`).digest('hex').slice(0,24);
         this.report('syncing',{discovered_sections:[inventoryKey]},'task_list');
        }
       }
      }
      catch(error){failed++;reason=error.code||'dom';this.issues.set(kind+':'+index,{course_index:index+1,section:kind});this.onInventory({phase:'failure',course_id:expectedIdentity.courseId,class_id:expectedIdentity.classId,kind,reason})}
     }
    }catch(error){failed+=2;reason=error.code||'dom';this.issues.set('course:'+index,{course_index:index+1,section:'course'});for(const kind of ['assignment','exam'])this.onInventory({phase:'failure',course_id:linkIdentity.courseId,class_id:linkIdentity.classId,kind,reason})}
    finally{if(tab)await tab.close().catch(()=>{})}
    this.visitedCourses.add(index);
   }
   const coverage=[...this.coverageIssues.values()].reduce((sum,value)=>({detail_pending:sum.detail_pending+value.detail_pending,unsupported:sum.unsupported+value.unsupported,media_pending:sum.media_pending+value.media_pending}),{detail_pending:0,unsupported:0,media_pending:0});
   const pending=Math.max(0,total-this.visitedCourses.size)+this.issues.size+coverage.detail_pending;
   const limited=coverage.unsupported>0||coverage.media_pending>0||rawTotal>total;
   const detailIssues=[...this.coverageIssues].flatMap(([key,value])=>{const [section,index]=key.split(':');return value.detail_pending||value.unsupported||value.media_pending?[{course_index:Number(index)+1,section}]:[]});
   const complete=!pending&&!limited;
   const state=complete?'connected':this.issues.size||coverage.detail_pending||limited?'partial':'syncing';
   this.report(state,{checked:true,checked_count:checked,captured_count:captured,failed_count:failed,pending_count:pending,course_count:total,course_checked:processed,discovery_complete:this.visitedCourses.size>=total&&this.issues.size===0,detail_pending_count:coverage.detail_pending,unsupported_detail_count:coverage.unsupported,media_pending_count:coverage.media_pending,coverage:limited?'list_only':state==='connected'?'complete':state==='syncing'?'unknown':'partial',...(limited?{error:'coverage'}:{}),issues:[...this.issues.values(),...detailIssues].slice(0,10)},state==='partial'?'task_list':'',reason);
   if(this.visitedCourses.size>=total)this.visitedCourses.clear();
  }catch(error){this.report(error.code==='expired'?'expired':'retrying',{checked_count:checked,captured_count:captured,failed_count:failed,pending_count:Math.max(1,this.lastTotal-this.cursor)},'task_navigation',error.code||'unexpected')}
 }
 async close(){const page=this.page;this.page=null;if(page)await page.close().catch(()=>{})}
}
module.exports={TaskCenterCollector};
