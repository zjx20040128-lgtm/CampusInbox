'use strict';
const ENDPOINT='http://127.0.0.1:8765/api/chaoxing/messages';
const RETRY='courseinbox-retry';
let serial=Promise.resolve();
const activeReads=new Set();
chrome.storage.onChanged.addListener((changes,area)=>{if(area==='local' && (changes.enabled?.newValue===false || changes.token))for(const controller of activeReads)controller.abort()});
async function permitted(token){const state=await chrome.storage.local.get(['enabled','token']);return state.enabled && state.token===token}
function ordered(work) {const next=serial.then(work);serial=next.catch(()=>{});return next}
function platformSender(sender) {
  if (sender.id!==chrome.runtime.id) return false;
  try {const u=new URL(sender.url);return (u.origin==='https://fe.chaoxing.com' && u.pathname.startsWith('/front/webim/')) || (u.origin==='https://notice.chaoxing.com' && (u.pathname==='/pc/notice/myNotice' || /^\/pc\/notice\/[^/]+\/detail$/.test(u.pathname))) || ['https://mooc1.chaoxing.com','https://mooc2-ans.chaoxing.com'].includes(u.origin)}
  catch {return false}
}
async function download(url) {
  const controller=new AbortController();activeReads.add(controller);const timer=setTimeout(()=>controller.abort(),15000);
  try {
  const response=await fetch(url,{credentials:'omit',signal:controller.signal});
  if(!response.ok || !/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(response.url))throw new Error('附件下载失败或链接已失效。');
  if(Number(response.headers.get('content-length'))>8*1024*1024)throw new Error('附件超过 8 MB。');
  const reader=response.body.getReader(),chunks=[];let length=0;
  while(true){const {value,done}=await reader.read();if(done)break;length+=value.length;if(length>8*1024*1024){await reader.cancel();throw new Error('附件超过 8 MB。')}chunks.push(value)}
  const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length}
  let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary);
  } finally{clearTimeout(timer);activeReads.delete(controller)}
}
async function prepare(job,token,readInstructions=true) {
  if(!['course_notice','task_center'].includes(job.kind))return job;
  const result=structuredClone(job);let budget=Math.max(0,Math.min(20000,30000-job.text.length-job.title.length-(job.attachments||[]).reduce((n,a)=>n+a.name.length+220,400)));
  result.attachments=[];
  for(const attachment of job.attachments||[]) {
    const item={...attachment,status:'listed',text:'',error:''};result.attachments.push(item);
    const instruction=/说明|要求|作业|任务|通知|安排|instructions?|assignment|requirements?|guidelines?/i.test(item.name) || /\.docx$/i.test(item.name);
    if(!readInstructions || !instruction){item.status='skipped';item.error=readInstructions?'原文件已关联，未自动提取文字。':'附件正文自动读取未启用。';continue}
    if(!/\.(docx|pdf|txt|md)$/i.test(item.name) || !/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(item.url||'') || item.size>8*1024*1024 || !budget){item.status='skipped';item.error='附件格式、链接或大小不支持自动读取。';continue}
    const current=await chrome.storage.local.get(['enabled','token']);if(!current.enabled || current.token!==token)throw new Error('同步已关闭；待传通知保留。');
    try {
      const content_base64=await download(item.url);
      if(!await permitted(token))throw new Error('同步已关闭；待传通知保留。');
      const response=await fetch('http://127.0.0.1:8765/api/chaoxing/attachments/extract',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({filename:item.name,content_base64}),signal:AbortSignal.timeout(10000)});
      if(!response.ok)throw new Error((await response.json()).error||'附件文字提取失败。');
      const extracted=await response.json();if(typeof extracted.text!=='string' || !extracted.text.trim())throw new Error('附件没有可提取的文字。');
      item.text=extracted.text.slice(0,budget);item.status=extracted.truncated || extracted.text.length>budget?'partial':'extracted';budget-=item.text.length;
      if(item.status==='partial')item.error='仅保留部分附件文字，请打开原文件核对。';
    } catch(error){if(!await permitted(token))throw error;item.status='failed';item.error=String(error.message).slice(0,250)}
  }
  return result;
}

async function flush() {
  const state=await chrome.storage.local.get(['enabled','token','queue','delivered','readInstructions','rejected','incomplete']);
  if (!state.enabled || !state.token) return;
  let queue=state.queue||[], delivered=state.delivered||0;
  for (let count=0;queue.length && count<100;count++) {
    const current=await chrome.storage.local.get(['enabled','token']);
    if(!current.enabled || !current.token || current.token!==state.token) return;
    try {
      const payload=await prepare(queue[0],state.token,state.readInstructions!==false);
      const still=await chrome.storage.local.get(['enabled','token']);if(!still.enabled || still.token!==state.token)return;
      const response=await fetch(ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+state.token},
        body:JSON.stringify(payload),signal:AbortSignal.timeout(6000)});
      if([400,422].includes(response.status)){
        const rejected=state.rejected||[];rejected.push(queue[0]);queue=queue.slice(1);state.rejected=rejected;
        await chrome.storage.local.set({queue,rejected,lastError:'有通知格式不受支持，已单独保留；其他通知继续发送。'});continue;
      }
      if (response.status!==200 && response.status!==201) throw new Error('HTTP '+response.status+'；请检查电脑服务或网页同步令牌。');
      const acknowledgement=typeof response.json==='function'?await response.json():{};
      const incomplete=(state.incomplete||[]).filter(job=>job.message_id!==payload.message_id);
      if(payload.attachments?.some(item=>item.status==='failed') || acknowledgement.attachment_pending || acknowledgement.attachment_conflict)incomplete.push(queue[0]);state.incomplete=incomplete;
      if(acknowledgement.attachment_conflict)await chrome.storage.local.set({sourceError:'附件新文字与已保存文字不一致；原文已保留，请核对原文件。'});
      queue=queue.slice(1);delivered++;
      await chrome.storage.local.set({incomplete});
      await chrome.storage.local.set({queue,delivered,lastSuccess:new Date().toISOString(),lastError:''});
    } catch (error) {
      await chrome.storage.local.set({lastError:'暂未发送成功：'+error.message});
      return;
    }
  }
}
async function capture(messages) {
  const state=await chrome.storage.local.get(['enabled','token','queue','rejected','incomplete']);
  if (!state.enabled || !state.token) return {accepted:[],disabled:true};
  const queue=state.queue||[], ids=new Set([...queue,...(state.rejected||[]),...(state.incomplete||[])].map(m=>m.message_id)), accepted=[];
  let bytes=JSON.stringify([queue,state.rejected||[],state.incomplete||[]]).length;
  for (const m of messages.slice(0,100)) {
    if (!m || !/^[A-Za-z0-9_-]{1,200}$/.test(m.message_id||'') || typeof m.text!=='string' || !m.text.trim() || m.text.length>30000) continue;
    if (ids.has(m.message_id)) {accepted.push(m.message_id);continue}
    const size=JSON.stringify(m).length;
    if (queue.length+(state.rejected?.length||0)+(state.incomplete?.length||0)>=500 || bytes+size>1500000) {
      await chrome.storage.local.set({lastError:'待传队列已满，请恢复电脑连接；未保存的消息将由网页再次尝试。'});break;
    }
    queue.push(m);ids.add(m.message_id);accepted.push(m.message_id);bytes+=size;
  }
  await chrome.storage.local.set({queue});
  await flush();
  return {accepted};
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  const fromOptions=sender.id===chrome.runtime.id && (sender.url||'').startsWith('chrome-extension://'+chrome.runtime.id+'/options.html');
  if(message?.type==='sync-state' && platformSender(sender)) {chrome.storage.local.get(['enabled','token']).then(state=>reply({enabled:Boolean(state.enabled&&state.token)}));return true}
  if(message?.type==='source-status' && platformSender(sender)) {chrome.storage.local.set({sourceError:String(message.error||'').slice(0,250)}).then(()=>reply({ok:true}));return true}
  if (message?.type==='capture' && platformSender(sender) && Array.isArray(message.messages)) {
    ordered(()=>capture(message.messages)).then(reply,error=>reply({accepted:[],error:error.message}));return true;
  }
  if (message?.type==='retry' && fromOptions) {
    ordered(async()=>{const state=await chrome.storage.local.get(['queue','rejected','incomplete']);const jobs=[...(state.queue||[]),...(state.rejected||[]),...(state.incomplete||[])];const unique=Array.from(new Map(jobs.map(job=>[job.message_id,job])).values());await chrome.storage.local.set({queue:unique,rejected:[],incomplete:[]});await flush()}).then(()=>reply({ok:true}),error=>reply({error:error.message}));return true;
  }
  reply({accepted:[],error:'不支持的页面或操作。'});return false;
});
async function initialize() {
  await chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
  await chrome.alarms.create(RETRY,{periodInMinutes:1});
}
chrome.runtime.onInstalled.addListener(()=>initialize());
chrome.runtime.onStartup.addListener(()=>initialize().then(()=>ordered(flush)));
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name===RETRY)ordered(flush)});
initialize().catch(()=>{});
