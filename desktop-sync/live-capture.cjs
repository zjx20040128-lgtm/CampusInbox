'use strict';
function sourceKind(value){
 try{
  const u=new URL(value);if(u.protocol!=='https:')return '';
  if(u.hostname==='fe.chaoxing.com'&&u.pathname==='/front/webim/index.html')return 'chat';
  if(u.hostname==='notice.chaoxing.com'&&u.pathname==='/pc/notice/myNotice')return 'notice';
  if(['mooc1.chaoxing.com','mooc2-ans.chaoxing.com'].includes(u.hostname)&&(/\/work\/list\b|\/exam\/list\b/.test(u.pathname)||u.pathname==='/visit/interaction'))return 'task';
 }catch{}return '';
}
function observePage(binding){
 const kind=sourceKind(location.href);if(!kind||window.__campusInboxLiveObserver)return;
 window.__campusInboxLiveObserver=true;
 const known=new Map(),observedRoots=new WeakSet();let initialized=false,timer;
 const identity=node=>['data-conversation-id','data-chat-id','data-cid','data-tid','data-id','id'].map(a=>node.getAttribute(a)).find(Boolean)||['data-conversation-id','data-chat-id','data-cid','data-tid','data-id'].map(a=>node.querySelector('['+a+']')?.getAttribute(a)).find(Boolean)||node.querySelector('a[href]')?.getAttribute('href')||node.querySelector('.name')?.textContent?.trim()||'';
 const signature=node=>((node.textContent||'')+Array.from(node.querySelectorAll('attachment-item')).map(host=>Array.from(host.shadowRoot?.querySelectorAll('.attach-info h1,.attach-info p')||[]).map(n=>n.textContent).join(' ')).join(' ')).replace(/(?:剩余|还剩)\s*[:：]?\s*(?:\d+(?:\.\d+)?\s*(?:天|小时|分钟|时|分|秒)\s*)+/g,'').replace(/\s+/g,' ').trim().slice(0,8000);
 function snapshot(){
  const rows=[];
  if(kind==='chat'){
   for(const host of document.querySelectorAll('.message-area attachment-item'))if(host.shadowRoot&&!observedRoots.has(host.shadowRoot)){
    observedRoots.add(host.shadowRoot);new MutationObserver(schedule).observe(host.shadowRoot,{childList:true,subtree:true,characterData:true});
   }
   for(const n of document.querySelectorAll('.conversation-list .conversation-item'))rows.push(['c:'+identity(n),signature(n),identity(n)]);
   const selected=document.querySelector('.conversation-list .conversation-item.is-selected'),current=selected?identity(selected):'';
   for(const n of document.querySelectorAll('.message-area .message-row[data-msg-id]'))rows.push(['m:'+n.getAttribute('data-msg-id'),signature(n),current]);
  }else{
   const selector=kind==='notice'?'.dataBody_item':'.bottomList li[data],[data-task-id],.work-list-item,.exam-list-item,a.color1';
   for(const n of document.querySelectorAll(selector))rows.push([n.getAttribute('data-id')||n.getAttribute('data-task-id')||n.getAttribute('data')||n.querySelector('[data-url]')?.getAttribute('data-url')||n.getAttribute('href')||signature(n),signature(n),'']);
  }
  if(!rows.length){
   // An unfinished navigation is not a new notification. Recognize a ready empty list.
   if(/暂无会话|暂无聊天|暂无消息|暂无通知|暂无课程|已经加载完/.test(document.body?.textContent||''))initialized=true;
   return;
  }
  const changed=[];
  for(const [key,value,conversation] of rows){if(initialized&&known.get(key)!==value)changed.push(conversation);known.set(key,value)}
  initialized=true;while(known.size>10000)known.delete(known.keys().next().value);
  if(changed.length&&typeof window[binding]==='function')window[binding]({kind,conversations:[...new Set(changed.filter(Boolean))].slice(0,100)}).catch(()=>{});
 }
 function schedule(){if(timer)return;timer=setTimeout(()=>{timer=undefined;snapshot()},750)}
 new MutationObserver(schedule).observe(document,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['data-msg-id','data-conversation-id','data-task-id','data-id','data-url']});
 schedule();window.addEventListener('pagehide',()=>clearTimeout(timer),{once:true});
}
async function installLiveCapture(context,onChange){
 const binding='__campusInboxDOMChanged';
 await context.exposeBinding(binding,({frame},event)=>{
  const kind=sourceKind(frame.url());if(!kind||event?.kind!==kind)return;
  const conversations=Array.isArray(event.conversations)?event.conversations.filter(v=>typeof v==='string'&&v.length<=180).slice(0,100):[];
  onChange({kind,conversations});
 });
 const script=`(()=>{const sourceKind=${sourceKind.toString()};(${observePage.toString()})(${JSON.stringify(binding)})})()`;
 await context.addInitScript({content:script});
 for(const page of context.pages())for(const frame of page.frames())await frame.evaluate(script).catch(()=>{});
}
module.exports={installLiveCapture,sourceKind};
