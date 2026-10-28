/* Read-only official-page collector. No native bridge, cookies or login fields. */
(function(root){
 'use strict';
 if(root.CourseInboxMobileReader)return;
 let noticeCursor=0,chatCursor=0;
 const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 function official(value){try{const u=new URL(value);return u.protocol==='https:'&&(u.hostname==='chaoxing.com'||u.hostname.endsWith('.chaoxing.com'))}catch{return false}}
 function visible(element){return Boolean(element&&Array.from(element.getClientRects()).some(rect=>rect.width>0&&rect.height>0)&&getComputedStyle(element).visibility==='visible')}
 function loginChallenge(){
  if(Array.from(document.querySelectorAll('input[type="password"],input[autocomplete="one-time-code"],#captcha,#captchaCode,#verifyCode,#verificationCode')).some(visible))return true;
  return Array.from(document.querySelectorAll('iframe')).some(frame=>{
   if(!visible(frame))return false;
   try{const u=new URL(frame.src);return u.origin==='https://passport2.chaoxing.com'&&/^\/(?:login|verify|verification|captcha)(?:\/|$)/.test(u.pathname)}catch{return false}
  });
 }
 function portalAuthenticated(){
  if(location.hostname==='mooc2-ans.chaoxing.com'&&location.pathname==='/visit/interaction'){
   return Array.from(document.querySelectorAll('#divbox .course-con #courseList .learnCourse,#divbox .course-con #courseList .teachCourse')).some(card=>visible(card)&&visible(card.querySelector('.course-cover'))&&visible(card.querySelector('.course-info .course-name')));
  }
  if(location.hostname!=='i.chaoxing.com'||!/^\/(?:base\/?)?$/.test(location.pathname))return false;
  if(Array.from(document.querySelectorAll('iframe')).some(frame=>visible(frame)&&/^https:\/\/notice\.chaoxing\.com\/pc\/notice\//.test(frame.src)))return true;
  if(!visible(document.querySelector('.header .user'))||!visible(document.querySelector('.con-left .user-block .user-name')))return false;
  // The menu may be collapsed while both account regions remain rendered.
  const labels=new Set(Array.from(document.querySelectorAll('.con-left .menu-list-ul li')).map(element=>element.textContent.trim()));
  return labels.has('课程')&&labels.has('消息');
 }
 function mode(){
  if(!official(location.href))return 'unsupported';
  if(location.hostname==='passport2.chaoxing.com'&&location.pathname.startsWith('/login')||document.querySelector('#quickCode'))return 'waiting_scan';
  if(loginChallenge())return 'unrecognized';
  if(location.hostname==='fe.chaoxing.com'&&location.pathname==='/front/webim/index.html')return 'chat';
  if(location.hostname==='notice.chaoxing.com'&&location.pathname.startsWith('/pc/notice/'))return 'notice';
  return 'portal';
 }
 async function chat(){
  const list=document.querySelector('.conversation-list');
  if(!list)return {state:'loading',messages:[]};
  const items=Array.from(list.querySelectorAll('.conversation-item')).slice(0,100);
  if(!items.length)return {state:/^(暂无会话|暂无聊天|暂无消息)$/.test(list.textContent.trim())?'connected':'loading',messages:[]};
  const names=items.map(el=>el.querySelector('.name')?.textContent.trim()||''),counts=new Map();for(const name of names)counts.set(name,(counts.get(name)||0)+1);
  const messages=[];let partial=false;
  const start=chatCursor%items.length;
  for(let i=0;i<Math.min(items.length,3);i++){
   const index=(start+i)%items.length;chatCursor=(index+1)%items.length;
   const name=names[index];if(!name||counts.get(name)!==1){partial=true;continue}
   const previous={header:document.querySelector('.chat-header .chat-name')?.textContent.trim()||'',selected:document.querySelector('.conversation-item.is-selected .name')?.textContent.trim()||'',ids:Array.from(document.querySelectorAll('.message-area .message-row[data-msg-id]')).map(el=>el.getAttribute('data-msg-id'))};
   items[index].click();
   function ready(){
    const header=document.querySelector('.chat-header .chat-name')?.textContent.trim()||'';
    const selected=document.querySelector('.conversation-item.is-selected .name')?.textContent.trim()||'';
    const rows=Array.from(document.querySelectorAll('.message-area .message-row[data-msg-id]'));
    if(header!==name||selected!==name||!document.querySelector('.message-area'))return false;
    if(previous.selected!==name&&previous.header&&header===previous.header)return false;
    if(rows.length&&previous.selected!==name&&rows.some(el=>previous.ids.includes(el.getAttribute('data-msg-id'))))return false;
    return rows.length>0||/^(暂无消息|暂无聊天记录|还没有消息)$/.test(document.querySelector('.message-area').textContent.trim());
   }
   for(let attempt=0;attempt<20&&!ready();attempt++)await wait(100);
   if(!ready()){partial=true;continue}
   for(const job of root.CourseInboxChaoxing.extractDocument(document).slice(-100))messages.push({...job,kind:'chat',url:location.href});
  }
  return {state:partial?'partial':'connected',messages};
 }
 async function notice(limit=5){
  const messages=[];
  if(/\/detail$/.test(location.pathname)){
   const row={url:location.href,title:document.querySelector('#title')?.textContent||'',time:'',sender:''};
   const job=root.CourseInboxNotices.extractDetail(document,row);if(job)messages.push(job);
   return {state:job?'connected':'loading',messages,listed_count:1,inspected_count:job?1:0,detail_count:messages.length,failed_count:0};
  }
  const list=document.querySelector('.dataBody');
  const rows=root.CourseInboxNotices.extractList(document,location.href);
  if(!list&&!rows.length)return {state:'loading',messages};
  if(!rows.length)return {state:/^(暂无通知|暂无消息|暂无数据)$/.test(list.textContent.trim())?'connected':'loading',messages,listed_count:0,inspected_count:0,detail_count:0,failed_count:0};
  let partial=false,failed=0;const start=noticeCursor%Math.max(1,rows.length);
  const count=Math.min(rows.length,limit);
  for(let i=0;i<count;i++){
   const row=rows[(start+i)%rows.length];noticeCursor=(start+i+1)%rows.length;
   try{
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
    try{
     const response=await fetch(row.url,{credentials:'same-origin',redirect:'error',signal:controller.signal}),html=await response.text();
     if(!response.ok||root.CourseInboxNotices.safeDetailURL(response.url)!==row.url||html.length>2000000)throw Error('detail');
     const doc=new DOMParser().parseFromString(html,'text/html');
     let job=root.CourseInboxNotices.extractDetail(doc,row);
     if(!job||(!job.text&&!job.attachments.length)){
      const dataUrl=root.CourseInboxNotices.detailDataURL(row.url);
      const dataResponse=await fetch(dataUrl,{credentials:'same-origin',redirect:'error',signal:controller.signal}),raw=await dataResponse.text();
      if(!dataResponse.ok||dataResponse.url!==dataUrl||raw.length>2000000)throw Error('detail_data');
      job=root.CourseInboxNotices.extractData(document,JSON.parse(raw),row);
     }
     if(!job)throw Error('content');messages.push(job);
    }finally{clearTimeout(timeout)}
   }catch{partial=true;failed++}
  }
  return {state:partial?'partial':'connected',messages,listed_count:rows.length,inspected_count:count,detail_count:messages.length,failed_count:failed};
 }
 async function poll(options={}){
  try{
  const current=mode();
  if(current==='chat'||current==='notice'){
   const limit=Number.isSafeInteger(options.notice_limit)?Math.max(1,Math.min(5,options.notice_limit)):5;
   const result=current==='chat'?await chat():await notice(limit);
   return {...result,authenticated:result.state==='connected'||result.state==='partial',url:location.href};
  }
  const authenticated=current==='portal'&&portalAuthenticated();
  return {state:current==='portal'?(authenticated?'authenticated':'unrecognized'):current,messages:[],authenticated,url:location.href};
  }catch{return {state:'error',messages:[],authenticated:false,url:location.href};}
 }
 root.CourseInboxMobileReader={poll};
})(globalThis);
