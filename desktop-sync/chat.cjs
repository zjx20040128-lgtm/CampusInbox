/* App-owned official webim DOM reader. Never submits or sends chat messages. */
'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const URL_CHAT='https://fe.chaoxing.com/front/webim/index.html';
const fault=code=>Object.assign(Error(code),{code});
function reason(error){
 if(['dom','expired','http_429','http_5xx','http_error','network','interrupted','closed'].includes(error?.code))return error.code;
 if(error?.name==='TimeoutError')return 'timeout';
 const message=String(error?.message||'');return /closed/i.test(message)?'closed':/net::|network/i.test(message)?'network':'unexpected';
}
class ChatCollector{
 constructor({context,accepted,isCurrent,onMessage,onStatus,cursor=''}){Object.assign(this,{context,accepted,isCurrent,onMessage,onStatus});this.page=null;this.cursor=typeof cursor==='string'?cursor:'';this.navigate=true;this.phase='chat_navigation';this.mediaGaps=new Map()}
 report(state,error='',checked=false,code='',counts={}){if(this.isCurrent())this.onStatus({state,error,checked,stage:state==='connected'?'':this.phase,reason:code,...counts,cursor:this.cursor})}
 prioritize(ids){
  this.priority=this.priority||new Set();for(const id of ids||[])this.priority.add(crypto.createHash('sha256').update(id).digest('hex'));
  while(this.priority.size>1000)this.priority.delete(this.priority.values().next().value);
 }
 async login(){
  try{
   if(!this.page||this.page.isClosed())return false;
   for(const frame of this.page.frames()){
    try{const u=new URL(frame.url());if(u.hostname==='passport2.chaoxing.com'&&u.pathname.startsWith('/login'))return true;
     if(u.hostname==='chaoxing.com'||u.hostname.endsWith('.chaoxing.com')){const qr=frame.locator('#quickCode');if(await qr.count()&&await qr.first().isVisible())return true}
    }catch{}
   }return false;
  }catch{return false}
 }
 async open(){
  if(!this.page||this.page.isClosed()){
   this.page=await this.context.newPage();this.page.setDefaultTimeout(8000);this.navigate=true;
   const owned=this.page,disconnected=()=>{if(this.isCurrent()&&this.page===owned)this.navigate=true};
   owned.on('close',disconnected);owned.on('websocket',socket=>{socket.on('close',disconnected);socket.on('socketerror',disconnected)});
  }
  for(let attempt=0;attempt<2;attempt++){
   if(!this.isCurrent())throw fault('interrupted');
   try{
    this.phase='chat_navigation';let response;
    if(this.navigate){response=await this.page.goto(URL_CHAT,{waitUntil:'domcontentloaded',timeout:20000});this.navigate=false}
    if(await this.login())throw fault('expired');
    const u=new URL(this.page.url());if(u.origin!=='https://fe.chaoxing.com'||u.pathname!=='/front/webim/index.html'){this.navigate=true;throw fault('dom')}
    const code=response?.status();if(code>=400){this.navigate=true;throw fault(code===429?'http_429':code>=500?'http_5xx':'http_error')}
    this.phase='chat_ready';await this.page.locator('.conversation-list').waitFor({state:'attached',timeout:20000});
    await this.page.waitForFunction(()=>{
     const list=document.querySelector('.conversation-list');if(!list)return false;
     const named=Array.from(list.querySelectorAll('.conversation-item .name')).some(node=>node.textContent.trim());
     const empty=/^(暂无会话|暂无聊天|暂无消息)$/.test(list.innerText.trim());return named||empty;
    },null,{timeout:20000});
    await this.page.evaluate(fs.readFileSync(path.join(__dirname,'../browser-companion/parser.js'),'utf8'));return;
   }catch(error){if(await this.login())throw fault('expired');if(error.code==='expired'||attempt===1||!this.isCurrent())throw error;await this.page.waitForTimeout(500)}
  }
 }
 async history(identity,name,initial){
  const found=new Map(initial.map(job=>[job.message_id,job]));let stable=0,complete=false,mediaCount=0;
  for(let step=0;step<8&&this.isCurrent();step++){
   const before=await this.page.evaluate(()=>{const area=document.querySelector('.message-area');return {count:area?.querySelectorAll('.message-row[data-msg-id]').length||0,top:area?.scrollTop||0,scrollable:Boolean(area&&area.scrollHeight>area.clientHeight+5),media_count:area?.querySelectorAll('.message-row img:not(.avatar):not(.sender-avatar),.message-row video,.message-row audio,.message-row canvas,.message-row object,.message-row embed,.message-row iframe,.message-row .bubble-file').length||0}});
   mediaCount=Math.max(mediaCount,before.media_count||0);
   if(!before.scrollable){complete=true;break}
   await this.page.evaluate(()=>{const area=document.querySelector('.message-area');if(area)area.scrollTop=0});
   await this.page.waitForTimeout(800);
   const current=await this.page.evaluate(({identity,name})=>{
    const selected=document.querySelector('.conversation-list .conversation-item.is-selected');
    const label=selected?.querySelector('.name')?.textContent?.trim()||'';
    const id=selected&&(['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>selected.getAttribute(attr)).find(Boolean)||selected.querySelector('[data-conversation-id]')?.getAttribute('data-conversation-id')||selected.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||selected.querySelector('[data-cid]')?.getAttribute('data-cid')||selected.querySelector('[data-tid]')?.getAttribute('data-tid')||selected.querySelector('[data-id]')?.getAttribute('data-id')||selected.querySelector('a[href]')?.getAttribute('href')||label);
    if(id!==identity||!document.querySelector('.chat-header .chat-name')?.textContent.trim())return null;
    const area=document.querySelector('.message-area');
    return {jobs:CourseInboxChaoxing.extractDocument(document),count:area?.querySelectorAll('.message-row[data-msg-id]').length||0,top:area?.scrollTop||0};
   },{identity,name});
   if(!current)return {jobs:[...found.values()],complete:false,media_count:mediaCount};
   const size=found.size;for(const job of current.jobs)found.set(job.message_id,job);
   if(found.size===size&&current.count===before.count&&current.top===0)stable++;else stable=0;
   if(stable>=1){complete=true;break}
  }
  return {jobs:[...found.values()],complete,media_count:mediaCount};
 }
 async sweep(){
  if(!this.isCurrent())return;this.report('syncing');
  try{
   await this.open();if(!this.isCurrent())return;
   const entries=await this.page.locator('.conversation-list .conversation-item').evaluateAll(items=>items.map((item,index)=>{
    const name=item.querySelector('.name')?.textContent?.trim()||'';
    const id=['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>item.getAttribute(attr)).find(Boolean)||item.querySelector('[data-conversation-id],[data-chat-id],[data-cid],[data-tid],[data-id]')?.getAttribute('data-conversation-id')||item.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||item.querySelector('[data-cid]')?.getAttribute('data-cid')||item.querySelector('[data-tid]')?.getAttribute('data-tid')||item.querySelector('[data-id]')?.getAttribute('data-id')||item.querySelector('a[href]')?.getAttribute('href')||name;
    return {index,name,id};
   }));
   const counts=new Map();for(const entry of entries){entry.cursor=crypto.createHash('sha256').update(String(entry.id||'')).digest('hex');counts.set(entry.cursor,(counts.get(entry.cursor)||0)+1)}
   let partial=false,pending=0,checked=0,captured=0,lastReason='';const failed=new Set();
   if(!entries.length){const empty=await this.page.evaluate(()=>/^(暂无会话|暂无聊天|暂无消息)$/.test(document.querySelector('.conversation-list')?.innerText.trim()||''));if(empty)this.mediaGaps.clear();this.report(empty?'connected':'partial',empty?'':'chat',true,empty?'':'dom',{checked_count:0,captured_count:0,failed_count:empty?0:1,pending_count:empty?0:1,coverage:empty?'loaded_text':'partial',media_pending_count:0});return}const cursorIndex=entries.findIndex(entry=>entry.cursor===this.cursor),start=cursorIndex>=0?(cursorIndex+1)%entries.length:0;
   const currentEntries=new Set(entries.map(entry=>entry.cursor));for(const key of this.mediaGaps.keys())if(!currentEntries.has(key))this.mediaGaps.delete(key);
   const rotated=entries.map((_,offset)=>entries[(start+offset)%entries.length]);
   const ordered=[...rotated.filter(e=>this.priority?.has(e.cursor)),...rotated.filter(e=>!this.priority?.has(e.cursor))];
   for(let offset=0;offset<entries.length&&checked<10&&this.isCurrent();offset++){
    const entry=ordered[offset],name=entry.name;this.cursor=entry.cursor;checked++;
    this.report('syncing','',false,'',{checked_count:checked,captured_count:captured});
    if(!name||name.length>100||counts.get(entry.cursor)!==1){partial=true;pending++;lastReason='dom';failed.add(entry.index+1);continue}
    try{
     this.phase='chat_conversation';
     const liveIndex=await this.page.locator('.conversation-list .conversation-item').evaluateAll((items,wanted)=>{
      const identity=node=>{const label=node.querySelector('.name')?.textContent?.trim()||'';return ['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>node.getAttribute(attr)).find(Boolean)||node.querySelector('[data-conversation-id]')?.getAttribute('data-conversation-id')||node.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||node.querySelector('[data-cid]')?.getAttribute('data-cid')||node.querySelector('[data-tid]')?.getAttribute('data-tid')||node.querySelector('[data-id]')?.getAttribute('data-id')||node.querySelector('a[href]')?.getAttribute('href')||label};
      const matches=items.flatMap((node,index)=>identity(node)===wanted?[index]:[]);return matches.length===1?matches[0]:-1;
     },entry.id);
     if(liveIndex<0){partial=true;pending++;lastReason='dom';failed.add(entry.index+1);continue}
     const item=this.page.locator('.conversation-list .conversation-item').nth(liveIndex);
     const currentId=await item.evaluate(node=>{
      const name=node.querySelector('.name')?.textContent?.trim()||'';
      return ['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>node.getAttribute(attr)).find(Boolean)||node.querySelector('[data-conversation-id]')?.getAttribute('data-conversation-id')||node.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||node.querySelector('[data-cid]')?.getAttribute('data-cid')||node.querySelector('[data-tid]')?.getAttribute('data-tid')||node.querySelector('[data-id]')?.getAttribute('data-id')||node.querySelector('a[href]')?.getAttribute('href')||name;
     });
     if(currentId!==entry.id){partial=true;pending++;lastReason='dom';failed.add(entry.index+1);continue}
     const previous=await this.page.evaluate(()=>{
      const identity=node=>{if(!node)return '';const name=node.querySelector('.name')?.textContent?.trim()||'';return ['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>node.getAttribute(attr)).find(Boolean)||node.querySelector('[data-conversation-id]')?.getAttribute('data-conversation-id')||node.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||node.querySelector('[data-cid]')?.getAttribute('data-cid')||node.querySelector('[data-tid]')?.getAttribute('data-tid')||node.querySelector('[data-id]')?.getAttribute('data-id')||node.querySelector('a[href]')?.getAttribute('href')||name};
      const selected=document.querySelector('.conversation-list .conversation-item.is-selected');
      return {name:document.querySelector('.chat-header .chat-name')?.textContent.trim()||'',selected:identity(selected),ids:Array.from(document.querySelectorAll('.message-area .message-row[data-msg-id]')).map(e=>e.getAttribute('data-msg-id'))};
     });
     await item.click({timeout:5000});this.phase='chat_content';
     await this.page.waitForFunction(({identity,name,previous})=>{
      const identityOf=node=>{if(!node)return '';const label=node.querySelector('.name')?.textContent?.trim()||'';return ['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>node.getAttribute(attr)).find(Boolean)||node.querySelector('[data-conversation-id]')?.getAttribute('data-conversation-id')||node.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||node.querySelector('[data-cid]')?.getAttribute('data-cid')||node.querySelector('[data-tid]')?.getAttribute('data-tid')||node.querySelector('[data-id]')?.getAttribute('data-id')||node.querySelector('a[href]')?.getAttribute('href')||label};
      const selected=document.querySelector('.conversation-list .conversation-item.is-selected');
      const header=document.querySelector('.chat-header .chat-name')?.textContent.trim();
      if(!header||identityOf(selected)!==identity)return false;
      if(previous.selected!==identity&&header===previous.name&&header!==name)return false;
      const rows=Array.from(document.querySelectorAll('.message-area .message-row[data-msg-id]'));
      const area=document.querySelector('.message-area');if(!area)return false;
      const empty=/^(暂无消息|暂无聊天记录|还没有消息)$/.test(area.innerText.trim());
      if(!rows.length)return empty;
      return previous.selected===identity||rows.every(e=>!previous.ids.includes(e.getAttribute('data-msg-id')));
     },{identity:entry.id,name,previous},{timeout:20000});
     if(!await this.page.locator('.message-area .message-row[data-msg-id]').count()){
      const empty=await this.page.evaluate(()=>/^(暂无消息|暂无聊天记录|还没有消息)$/.test(document.querySelector('.message-area')?.innerText.trim()||''));
      if(!empty){pending++;partial=true;lastReason='dom';failed.add(entry.index+1);continue}
     }
     if(!this.isCurrent())return;
     const jobs=await this.page.evaluate(({identity,name,previous})=>{
      const identityOf=node=>{if(!node)return '';const label=node.querySelector('.name')?.textContent?.trim()||'';return ['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(attr=>node.getAttribute(attr)).find(Boolean)||node.querySelector('[data-conversation-id]')?.getAttribute('data-conversation-id')||node.querySelector('[data-chat-id]')?.getAttribute('data-chat-id')||node.querySelector('[data-cid]')?.getAttribute('data-cid')||node.querySelector('[data-tid]')?.getAttribute('data-tid')||node.querySelector('[data-id]')?.getAttribute('data-id')||node.querySelector('a[href]')?.getAttribute('href')||label};
      const selected=document.querySelector('.conversation-list .conversation-item.is-selected');
      const header=document.querySelector('.chat-header .chat-name')?.textContent.trim();
      const rows=Array.from(document.querySelectorAll('.message-area .message-row[data-msg-id]'));
      if(!header||header.length>100||identityOf(selected)!==identity)return null;
      if(previous.selected!==identity&&header===previous.name&&header!==name)return null;
      if(rows.length&&previous.selected!==identity&&rows.some(e=>previous.ids.includes(e.getAttribute('data-msg-id'))))return null;
      return CourseInboxChaoxing.extractDocument(document);
     },{identity:entry.id,name,previous});
     if(!jobs){partial=true;pending++;lastReason='dom';failed.add(entry.index+1);continue}
     const emitted=new Set();
     const deliver=job=>{if(this.isCurrent()&&!this.accepted.has(job.message_id)&&!emitted.has(job.message_id)){emitted.add(job.message_id);this.onMessage({kind:'chat',...job});captured++}};
     for(const job of jobs)deliver(job); // Send visible new content before loading older history.
     let loaded;
     try{loaded=await this.history(entry.id,name,jobs)}
     catch{loaded={jobs,complete:false}}
     this.mediaGaps.set(entry.cursor,loaded.media_count||0);
     if(!loaded.complete){partial=true;pending++;lastReason='timeout';failed.add(entry.index+1)}
     for(const job of loaded.jobs){if(!this.isCurrent())return;deliver(job)}
     this.priority?.delete(entry.cursor);
    }catch(error){if(!this.isCurrent())return;if(await this.login())throw fault('expired');partial=true;pending++;lastReason=reason(error);failed.add(entry.index+1);this.report('partial','chat',false,lastReason,{checked_count:checked,captured_count:captured,failed_count:pending,pending_count:pending,issues:[...failed].map(conversation_index=>({conversation_index}))})}
   }
   const failedCount=pending;
   pending+=Math.max(0,entries.length-checked);
   const mediaCount=[...this.mediaGaps.values()].reduce((sum,value)=>sum+value,0);
   for(const entry of entries)if(this.mediaGaps.get(entry.cursor))failed.add(entry.index+1);
   const incomplete=partial||pending||mediaCount;
   this.report(incomplete?'partial':'connected',mediaCount&&!partial&&!pending?'coverage':incomplete?'chat':'',true,partial||pending?(lastReason||'dom'):'',{checked_count:checked,captured_count:captured,failed_count:failedCount,pending_count:pending,media_pending_count:mediaCount,coverage:incomplete?'partial':'loaded_text',issues:[...failed].map(conversation_index=>({conversation_index}))});
  }catch(error){if(this.isCurrent()){const code=reason(error);this.report(code==='expired'?'expired':'retrying',code==='expired'?'expired':'chat',false,code)}}
 }
 async close(){const page=this.page;this.page=null;if(page)await page.close().catch(()=>{})}
}
module.exports={ChatCollector};
