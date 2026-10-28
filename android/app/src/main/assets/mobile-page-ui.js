/* Phone presentation only. Original official nodes, input, links and readers stay intact. */
(function(root){
 'use strict';
 const url=new URL(location.href);
 if(url.protocol!=='https:'||url.username||url.password||url.port&&url.port!=='443')return;
 const path=url.pathname.replace(/\/+$/,'')||'/';
 const portal=url.hostname==='i.chaoxing.com'&&['/','/base'].includes(path);
 const course=url.hostname==='mooc2-ans.chaoxing.com'&&path==='/visit/interaction';
 const chat=url.hostname==='fe.chaoxing.com'&&path==='/front/webim/index.html';
 const noticeList=url.hostname==='notice.chaoxing.com'&&path==='/pc/notice/myNotice';
 const noticeDetail=url.hostname==='notice.chaoxing.com'&&/^\/pc\/notice\/[^/]+\/detail$/.test(path);
 const notice=noticeList||noticeDetail;
 if(!portal&&!course&&!chat&&!notice)return;
 if(root.CourseInboxMobilePageUI){root.CourseInboxMobilePageUI.apply();return;}
 function kind(){
  if(portal&&document.querySelector('.header .user')&&document.querySelector('.con .con-left .user-block')&&document.querySelector('.con .con-right .right-con #mainright'))return 'portal';
  if(course&&document.querySelector('#divbox .course-tab')&&document.querySelector('.course-con #courseList'))return 'course';
  if(chat&&document.querySelector('.conversation-list')&&document.querySelector('.message-area')&&document.querySelector('.chat-header'))return 'chat';
  if(noticeDetail&&document.body)return 'detail';
  if(noticeList&&document.body)return 'notice';
  return '';
 }
 function button(id,label,parent,action){let el=document.getElementById(id);if(!el){el=document.createElement('button');el.id=id;el.type='button';el.textContent=label;el.className='ci-mobile-action';el.addEventListener('click',action);parent.insertBefore(el,parent.firstChild);}return el;}
 function frameEntry(){
  const frame=document.querySelector('.con-right .right-con #mainright #frame_content');let target='',label='';
  try{
   const u=new URL(frame?.getAttribute('src')||'',location.href);
   if(u.protocol==='https:'&&!u.username&&!u.password&&(!u.port||u.port==='443')){
    if(u.hostname==='mooc2-ans.chaoxing.com'&&u.pathname==='/visit/interaction')label='展开课程页';
    else if(u.hostname==='fe.chaoxing.com'&&u.pathname==='/front/webim/index.html')label='展开聊天消息';
    else if(u.hostname==='notice.chaoxing.com'&&/^\/pc\/notice\/(?:myNotice|[^/]+\/detail)$/.test(u.pathname))label='展开课程通知';
    if(label)target=u.href;
   }
  }catch{}
  let link=document.getElementById('ci-open-official-page');
  if(target){
   if(!link){link=document.createElement('a');link.id='ci-open-official-page';link.className='ci-mobile-action';frame.parentElement.insertBefore(link,frame);}
   if(link.textContent!==label)link.textContent=label;
   if(link.getAttribute('href')!==target)link.href=target;
   frame.setAttribute('data-ci-deferred-frame','true');
  }else{if(frame)frame.removeAttribute('data-ci-deferred-frame');if(link)link.remove();}
 }
 function chatLayout(){
  const list=document.querySelector('.conversation-list'),area=document.querySelector('.message-area');
  let layout=list.parentElement;while(layout&&!layout.contains(area))layout=layout.parentElement;
  if(!layout)return;
  layout.setAttribute('data-ci-chat-layout','true');
  for(let node=layout;node&&node!==document.body;node=node.parentElement)node.setAttribute('data-ci-page-fit','true');
  function branch(node){while(node.parentElement&&node.parentElement!==layout)node=node.parentElement;return node;}
  const listPanel=branch(list),messagePanel=branch(area);
  if(listPanel!==messagePanel){listPanel.setAttribute('data-ci-chat-list-panel','true');messagePanel.setAttribute('data-ci-chat-message-panel','true');}
  for(const el of document.querySelectorAll('.chat-header,.message-area,textarea,[contenteditable]'))for(let node=el.parentElement;node&&node!==layout;node=node.parentElement)node.setAttribute('data-ci-page-fit','true');
  const toggle=button('ci-conversations','会话列表',layout,()=>{const open=document.body.getAttribute('data-ci-conversations')!=='closed';document.body.setAttribute('data-ci-conversations',open?'closed':'open');toggle.setAttribute('aria-expanded',String(!open));});
  toggle.setAttribute('aria-expanded',String(document.body.getAttribute('data-ci-conversations')!=='closed'));
 }
 function apply(){
  const page=kind();if(!page||!document.body)return false;
  let viewport=document.querySelector('meta[name="viewport"]');if(!viewport){viewport=document.createElement('meta');viewport.name='viewport';document.head.appendChild(viewport);}if(viewport.content!=='width=device-width, initial-scale=1')viewport.content='width=device-width, initial-scale=1';
  document.body.setAttribute('data-ci-mobile-page',page);
  if(!document.getElementById('ci-mobile-page-style')){
   const style=document.createElement('style');style.id='ci-mobile-page-style';style.textContent=`
html{min-width:0!important;height:auto!important}
body[data-ci-mobile-page]{box-sizing:border-box;width:100%!important;min-width:0!important;max-width:100%!important;height:auto!important;min-height:100vh;margin:0!important;padding:12px!important;overflow:auto!important;background:#f4f6fb;font:16px/1.6 system-ui,-apple-system,"Microsoft YaHei",sans-serif}
body[data-ci-mobile-page] *,body[data-ci-mobile-page] *:before,body[data-ci-mobile-page] *:after{box-sizing:border-box}
.ci-mobile-action{display:block;width:100%;min-height:44px;padding:10px 14px!important;margin:0 0 12px!important;border:1px solid #dbe7fb;border-radius:12px;background:#fff;color:#397dea;text-align:center;text-decoration:none;font:500 16px/1.5 system-ui;cursor:pointer;white-space:normal}
body[data-ci-mobile-page="portal"] .header,body[data-ci-mobile-page="portal"] .space-unit,body[data-ci-mobile-page="portal"] .space-con,body[data-ci-mobile-page="portal"] .con,body[data-ci-mobile-page="portal"] .con-left,body[data-ci-mobile-page="portal"] .con-right,body[data-ci-mobile-page="portal"] .right-con,body[data-ci-mobile-page="portal"] #mainright{position:static!important;inset:auto!important;transform:none!important;float:none!important;width:100%!important;min-width:0!important;max-width:100%!important;height:auto!important;min-height:0!important;margin:0!important;padding:0!important}
body[data-ci-mobile-page="portal"] .header{border-radius:12px;padding:10px!important;overflow:visible!important}
body[data-ci-mobile-page="portal"] .header h3{font-size:16px;white-space:normal}
body[data-ci-mobile-page="portal"] .header .nav{display:flex;flex-wrap:wrap;float:none!important;width:auto!important;margin:0;padding:0}
body[data-ci-mobile-page="portal"] .header .nav>li{float:none!important;max-width:100%}
body[data-ci-mobile-page="portal"] .user-block{height:auto!important;min-height:44px;padding:8px!important;display:flex;align-items:center;gap:8px}
body[data-ci-mobile-page="portal"] .user-block .head-img{width:32px!important;height:32px!important}
body[data-ci-mobile-page="portal"] .user-name{width:auto!important;margin:0!important;line-height:1.6!important;font-size:14px!important;white-space:normal}
body[data-ci-mobile-page="portal"] .menu-list,body[data-ci-mobile-page="portal"] .mCustomScrollBox,body[data-ci-mobile-page="portal"] .mCSB_container{width:100%!important;height:auto!important;max-height:none!important;overflow:visible!important;margin:0!important;position:static!important;transform:none!important}
body[data-ci-mobile-page="portal"] .menu-list-ul{margin:0;padding:0;list-style:none}
body[data-ci-mobile-page="portal"] .menu-list-ul>li{min-height:44px;height:auto!important;padding:8px 12px!important;line-height:1.6!important;font-size:16px}
body[data-ci-mobile-page="portal"]:not([data-ci-menu="open"]) .menu-list{display:none!important}
body[data-ci-mobile-page="portal"] .menu-slide,body[data-ci-mobile-page="portal"] .mCSB_scrollTools{display:none!important}
body[data-ci-mobile-page="portal"] #frame_content{width:100%!important;max-width:100%!important;min-width:0!important;border:0}
body[data-ci-mobile-page="portal"] #frame_content[data-ci-deferred-frame]{display:none!important}
body[data-ci-mobile-page="course"] .box,body[data-ci-mobile-page="course"] .content,body[data-ci-mobile-page="course"] .main,body[data-ci-mobile-page="course"] .course-con,body[data-ci-mobile-page="course"] .course-list-con,body[data-ci-mobile-page="course"] .courselistArea,body[data-ci-mobile-page="course"] .course-list,body[data-ci-mobile-page="course"] .course-list>div{width:100%!important;max-width:100%!important;min-width:0!important;height:auto!important;min-height:0!important;margin-left:0!important;margin-right:0!important;position:static!important;transform:none!important;padding:0!important}
body[data-ci-mobile-page="course"] .main{background:white;border-radius:16px;overflow:visible}
body[data-ci-mobile-page="course"] .course-tab{display:flex;flex-wrap:wrap;height:auto!important;padding:0 8px!important;font-size:16px}
body[data-ci-mobile-page="course"] .course-tab .tab-item{flex:1;min-height:44px;margin:0!important;padding:12px 8px!important;line-height:1.5!important;font-size:16px!important}
body[data-ci-mobile-page="course"] .btn_group{display:flex;flex-wrap:wrap;gap:10px;padding:12px!important;width:100%!important}
body[data-ci-mobile-page="course"] .btn_group>a{margin:0!important;max-width:100%}
body[data-ci-mobile-page="course"] .btn_group>.fr{float:none!important;width:100%!important;max-width:100%}
body[data-ci-mobile-page="course"] .dataSearch{margin:0!important;width:100%!important;max-width:100%;float:none!important}
body[data-ci-mobile-page="course"] .course-list{padding:12px!important;font-size:14px}
body[data-ci-mobile-page="course"] .course-list .course,body[data-ci-mobile-page="course"] .course-list>.learnCourse,body[data-ci-mobile-page="course"] .course-list>.teachCourse{float:none!important;display:block;width:100%!important;height:auto!important;margin:0 0 18px!important;padding:0!important}
body[data-ci-mobile-page="course"] .course-cover{width:100%!important;max-width:100%;height:auto!important;aspect-ratio:16/9}
body[data-ci-mobile-page="course"] .course-cover>a,body[data-ci-mobile-page="course"] .course-cover img{width:100%!important;height:100%!important;max-width:100%;object-fit:cover}
body[data-ci-mobile-page="course"] .course-info{width:100%!important;max-width:100%;padding:0 8px 12px!important}
body[data-ci-mobile-page="course"] .course-info h3{width:100%!important;font-size:18px!important;height:auto!important;line-height:1.5}
body[data-ci-mobile-page="course"] .course-info p{font-size:14px!important;line-height:1.6!important}
body[data-ci-mobile-page="course"] .course-name{max-width:100%!important;height:auto!important;white-space:normal!important;overflow-wrap:anywhere;-webkit-line-clamp:unset!important}
body[data-ci-mobile-page="course"] #to_top{position:static!important;width:100%!important;margin:0!important;display:flex;flex-wrap:wrap;gap:8px}
body[data-ci-mobile-page="course"] .archiveCourseBtn{padding:12px!important;display:flex;flex-wrap:wrap;gap:10px}
body[data-ci-mobile-page="chat"] [data-ci-page-fit],body[data-ci-mobile-page="chat"] [data-ci-chat-list-panel],body[data-ci-mobile-page="chat"] [data-ci-chat-message-panel]{position:static!important;inset:auto!important;transform:none!important;float:none!important;width:100%!important;min-width:0!important;max-width:100%!important;height:auto!important;min-height:0!important;margin:0!important}
body[data-ci-mobile-page="chat"] [data-ci-chat-layout]{display:flex!important;flex-direction:column!important;width:100%!important;min-width:0!important;height:auto!important}
body[data-ci-mobile-page="chat"] .conversation-list{width:100%!important;max-height:32vh!important;height:auto!important;overflow-y:auto!important}
body[data-ci-mobile-page="chat"][data-ci-conversations="closed"] [data-ci-chat-list-panel],body[data-ci-mobile-page="chat"][data-ci-conversations="closed"] .conversation-list{display:none!important}
body[data-ci-mobile-page="chat"] .conversation-item{min-height:44px;white-space:normal}
body[data-ci-mobile-page="chat"] .chat-header{position:static!important;width:100%!important;height:auto!important;min-height:44px;font-size:18px}
body[data-ci-mobile-page="chat"] .message-area{width:100%!important;min-width:0!important;height:45vh!important;min-height:180px;max-height:60vh;overflow:auto!important}
body[data-ci-mobile-page="chat"] .message-row{max-width:100%!important;min-width:0!important}
body[data-ci-mobile-page="chat"] .bubble-text{max-width:100%!important;white-space:pre-wrap!important;overflow-wrap:anywhere;font-size:16px!important;line-height:1.6!important}
body[data-ci-mobile-page="chat"] textarea,body[data-ci-mobile-page="chat"] [contenteditable],body[data-ci-mobile-page="course"] input:not([type="hidden"]){max-width:100%!important;min-width:0!important;font-size:16px!important}
body[data-ci-mobile-page="chat"] textarea{width:100%!important;min-height:64px}
body[data-ci-mobile-page="notice"] .noticeMain,body[data-ci-mobile-page="detail"] .noticeMain,body[data-ci-mobile-page="notice"] .centerMain_fixed,body[data-ci-mobile-page="notice"] .dataCon,body[data-ci-mobile-page="notice"] .dataBody{width:100%!important;min-width:0!important;max-width:100%!important;height:auto!important;margin:0!important;padding:0!important;position:static!important}
body[data-ci-mobile-page="notice"]{overflow-x:hidden!important}
body[data-ci-mobile-page="notice"] *{min-width:0!important;max-width:100%!important}
body[data-ci-mobile-page="notice"] img{height:auto!important;object-fit:contain}
body[data-ci-mobile-page="notice"] .fixfill{display:none!important}
body[data-ci-mobile-page="notice"] .loadMore{position:static!important;inset:auto!important;width:100%!important;max-width:100%!important;margin:0!important}
body[data-ci-mobile-page="notice"] .centerMain_head,body[data-ci-mobile-page="notice"] .mainHead,body[data-ci-mobile-page="notice"] .bnt_group,body[data-ci-mobile-page="notice"] .head_right{width:100%!important;height:auto!important;display:flex;flex-wrap:wrap;gap:8px;float:none!important;padding:8px 0!important}
body[data-ci-mobile-page="notice"] .dataBody_item,body[data-ci-mobile-page="notice"] .openNotice{width:100%!important;min-width:0!important;height:auto!important;min-height:44px;white-space:normal!important;padding:8px 0!important}
body[data-ci-mobile-page="notice"] .notice_title{display:block!important;width:100%!important;max-width:100%;height:auto!important;white-space:normal!important;overflow-wrap:anywhere;font-size:16px!important;line-height:1.6!important}
body[data-ci-mobile-page="notice"] .notice_time,body[data-ci-mobile-page="notice"] .receiverName{font-size:13px!important;line-height:1.6;white-space:normal}
body[data-ci-mobile-page="detail"] #title{font-size:22px!important;line-height:1.5;white-space:normal;overflow-wrap:anywhere}
body[data-ci-mobile-page="detail"] .noticeContent{width:100%!important;max-width:100%!important;min-width:0!important;font-size:16px!important;line-height:1.7;overflow-wrap:anywhere}
body[data-ci-mobile-page="detail"] .noticeContent img,body[data-ci-mobile-page="detail"] .noticeContent iframe,body[data-ci-mobile-page="detail"] .noticeContent video{max-width:100%!important}
body[data-ci-mobile-page="detail"] .noticeContent img{height:auto!important}
body[data-ci-mobile-page="detail"] .noticeContent table,body[data-ci-mobile-page="detail"] .noticeContent pre{display:block;max-width:100%!important;overflow:auto!important}
body[data-ci-mobile-page="notice"] .popDiv,body[data-ci-mobile-page="detail"] .popDiv{max-width:calc(100vw - 24px)!important;max-height:85vh;overflow:auto}
`;document.head.appendChild(style);
  }
  if(page==='portal'){
   const toggle=button('ci-official-menu','官方菜单',document.querySelector('.con'),()=>{const open=document.body.getAttribute('data-ci-menu')==='open';document.body.setAttribute('data-ci-menu',open?'closed':'open');toggle.setAttribute('aria-expanded',String(!open));});toggle.setAttribute('aria-expanded',String(document.body.getAttribute('data-ci-menu')==='open'));frameEntry();
  }else if(page==='chat')chatLayout();
  return true;
 }
 root.CourseInboxMobilePageUI={apply};apply();
 const observer=new MutationObserver(()=>apply());observer.observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['src']});
})(globalThis);
