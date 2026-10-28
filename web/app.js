'use strict';
const $ = (selector, parent=document) => parent.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusNames={pending:'待开始',in_progress:'待开始',done:'已做完',submitted:'已提交',cancelled:'已取消'};
const kindNames={assignment:'作业',experiment:'实验',exam:'考试',project:'项目',presentation:'汇报',other:'其他'};
let token='', state={tasks:[],proposals:[],messages:[],summary:{},agent:{mode:'rules'}},settings={};
let view='today', inboxTab='pending', month=new Date(cnLocalTime().slice(0,10)+'T12:00:00'),detailId=null,toastTimer,calendarClockTimer,calendarRenderedDate='';
let supplementSourceId='',supplementGeneration=0;
let messageDetailGeneration=0,messageDetailCurrent=null;
let mobileRemindersTimer=null,mobileRemindersGeneration=0,mobileRemindersRequest=0,mobileRemindersStatus=null,mobileRemindersBusy=false;
const MESSAGE_PAGE_SIZE=20;
const messageDeadlineFilters={from:'',to:''};
let messagePage={items:[],total:0,limit:MESSAGE_PAGE_SIZE,offset:0},messagePageOffset=0,messagePageRequest=0,cleanupIds=[];
const selectedMessages=new Set();
const filters={search:'',course:'',status:'active',deadline:'all',deadlineFrom:'',deadlineTo:''};
const content=$('#content');
function cnLocalTime(date=new Date()){return new Date(date.getTime()+8*3600000).toISOString().slice(0,16)}
function formatDeadline(value){
  if(!value)return '截止待明确';
  const date=value.slice(0,10).replaceAll('-','.');
  return value.length===10 ? date+'（时刻未明确）' : date+' '+value.slice(11,16);
}
function dateLabel(value){return value ? value.slice(0,10).replaceAll('-','.')+' '+value.slice(11,16) : ''}
function isCalendarTaskOverdue(task,now=new Date()){
  if(!task.deadline||['submitted','cancelled'].includes(task.status))return false;
  return task.deadline.length===10?task.deadline<cnLocalTime(now).slice(0,10):new Date(task.deadline).getTime()<now.getTime();
}
function isUnstartedOverdue(task){return ['pending','in_progress'].includes(task.status)&&isCalendarTaskOverdue(task)}
function calendarNowLabel(now=new Date()){return '北京时间 '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now)}
function updateCalendarClock(){const clock=$('#calendarNow');if(!clock)return;const now=new Date();clock.textContent=calendarNowLabel(now);clock.dateTime=now.toISOString()}
function dueLabel(task){
  if(!['submitted','cancelled'].includes(task.status)&&task.checkin_verification&&task.checkin_verification!=='verified')return {text:task.checkin_verification==='ended'?'签到已结束':'签到待核验',color:'amber'};
  if(!task.deadline)return {text:'截止待明确',color:'amber'};
  if(task.status==='submitted')return {text:'已手动确认提交',color:'green'};
  if(task.status==='cancelled')return {text:'已取消',color:''};
  if(task.deadline.length===10){
    const today=cnLocalTime().slice(0,10);
    return {text:task.deadline<today?'日期已过':task.deadline===today?'今天截止 · 时刻待核对':'日期截止 · 时刻待核对',color:task.deadline<today?'red':'amber'};
  }
  const hours=(new Date(task.deadline)-Date.now())/3600000;
  return hours<=0 ? {text:'已逾期',color:'red'} : hours<24 ? {text:hours<1?'不足 1 小时截止':Math.ceil(hours)+' 小时后截止',color:hours<2?'red':'amber'} : {text:Math.ceil(hours/24)+' 天后截止',color:'green'};
}
function pill(text,color=''){return `<span class="pill ${esc(color)}">${esc(text)}</span>`}
function toast(message,error=false,action=null){
  clearTimeout(toastTimer);const box=$('#toast');box.textContent=message;box.className='toast'+(error?' error':'');box.hidden=false;
  if(action){
    const button=document.createElement('button');button.className='toast-action';button.textContent=action.label;
    button.addEventListener('click',async event=>{event.stopPropagation();clearTimeout(toastTimer);button.disabled=true;try{await action.run()}catch(error){toast(error.message,true)}finally{button.disabled=false}});
    box.append(button);
  }
  toastTimer=setTimeout(()=>box.hidden=true,action?12000:5500);
}
function taskStatusSaved(task,previous){
  if(['cancelled','submitted'].includes(task.status)&&previous!==task.status)toast(task.status==='submitted'?'已记为提交，可撤销本次记录':'任务已取消，也可在“全部任务”中恢复',false,{label:'撤销',run:()=>restoreTask(task.id,task.version,previous,task.status)});
  else toast(task.status==='done'?'已做完，记得在原平台提交':'任务状态已保存');
}
function confirmTaskStatus(task,status){
  if(!['cancelled','submitted'].includes(status)||task.status===status)return Promise.resolve(true);
  const dialog=$('#statusConfirmDialog');
  if(dialog.open)return Promise.resolve(false);
  $('#statusConfirmText').textContent='将“'+task.title+'”标记为“'+statusNames[status]+'”。';
  dialog.returnValue='';
  return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal()});
}
async function restoreTask(id,version,previous=null,expected='cancelled'){
  const current=await json('/api/tasks/'+id);
  if(current.version!==version||current.status!==expected){
    await refresh();
    if($('#taskDialog').open&&detailId===id)await openTask(id);
    throw new Error('任务已更新，请核对后再恢复。');
  }
  const transition=current.history.find(item=>item.after?.status===expected&&item.before?.status&&item.before.status!==expected);
  const status=previous||transition?.before.status||'pending';
  const restored=await json('/api/tasks/'+id,{method:'PATCH',body:{status,expected_version:version}});
  await refresh();
  if($('#taskDialog').open&&detailId===id)await openTask(id);
  toast('任务已恢复为“'+statusNames[restored.status]+'”');
}
async function api(path,options={}){
  const headers={...options.headers,Authorization:'Bearer '+token};
  if(options.body!==undefined){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body)}
  const response=await fetch(path,{...options,headers});
  if(!response.ok){let result;try{result=await response.json()}catch{result={error:'服务返回了无效响应。'}}throw new Error(result.error||'请求失败')}
  return response;
}
async function json(path,options){return (await api(path,options)).json()}
async function busy(button,fn){
  if(!button || button.disabled)return;
  const old=button.innerHTML;button.disabled=true;button.setAttribute('aria-busy','true');button.textContent='处理中…';
  try{return await fn()}finally{if(button.textContent==='处理中…'){button.removeAttribute('aria-busy');button.disabled=false;button.innerHTML=old}}
}
async function refresh(render=true,next=null){
  state=next||await json('/api/state');
  $('#taskBadge').textContent=state.tasks.filter(t=>taskMatchesStatus(t,'active',new Date())).length;
  $('#inboxBadge').textContent=state.proposals.length;
  $('#modeName').textContent=state.agent.mode==='agent'?'规则 + 模型辅助模式':'本地规则模式';
  $('#modeHint').textContent=state.agent.description;$('#modeName').title=state.agent.description||'';
  $('.sync-label').innerHTML='<span class="local-dot"></span>本地已连接';
  if(render)renderView();
}
function intro(title,subtitle,eyebrow='MY LEARNING DESK'){
  const now=new Date();
  return `<div class="page-intro"><div><h1>${esc(title)}</h1></div><div class="date-block"><strong>${esc(new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'}).format(now))}</strong></div></div>`;
}
function empty(title,text,button=''){
  return `<div class="empty-state"><span class="empty-icon">◇</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${button}</div>`;
}
function taskOptions(selected,task=null){
  const current=selected==='in_progress'?'pending':selected;
  return Object.entries(statusNames).filter(([value])=>value!=='in_progress').map(([v,n])=>`<option value="${v}" ${current===v?'selected':''}>${task&&v==='pending'&&isUnstartedOverdue(task)?'已逾期':n}</option>`).join('');
}
function priority(task){
  const due=dueLabel(task);
  return `<div class="priority-item"><span class="course-icon">${esc((task.course||'任务').slice(0,2))}</span><div class="priority-body"><h3>${esc(task.title)}</h3><p>${task.scope?esc(task.scope)+' · ':''}${esc(kindNames[task.kind])} ${task.sample?'· 示例':''}</p><div class="priority-meta">${pill(task.course||'未填写课程','outline')}${pill(due.text,due.color)}${task.status==='done'?pill('已做完 · 待提交','amber'):''}</div></div><button class="priority-action" data-detail="${task.id}" aria-label="查看 ${esc(task.title)}">↗</button></div>`;
}
function isCompanionDemo(message){return message.text.startsWith('【手机伴侣示例】')}
function messageSourceLabel(message){
  if(message.chat_import)return (message.chat_import.platform==='wechat'?'微信':'QQ')+'（文本导入） · '+message.chat_import.conversation;
  if(message.source!=='Android · com.chaoxing.mobile')return message.source;
  return (isCompanionDemo(message)?'手机伴侣示例':'学习通')+'（Android · com.chaoxing.mobile）';
}
function isSummaryOnly(message){
  return message.source==='Android · com.chaoxing.mobile' &&
    message.text.replace(/\s+/g,'')==='您有一条新消息请点击查看';
}
function summaryHelp(message){
  return isSummaryOnly(message)?'<p class="helper">此条仅收到学习通系统通知摘要，无法从通知中读取消息正文。</p><button class="text-button" data-open-import>导入完整内容</button>':'';
}
function recentMessagePreview(){
  const message=state.messages.find(m=>!m.sample&&!isCompanionDemo(m));
  if(!message)return '';
  const excerpt=message.text.slice(0,110)+(message.text.length>110?'…':'');
  return `<div class="review-preview recent-message-preview">${pill('已收到','green')}<h3>${esc(messageSourceLabel(message))}</h3><p>${esc(messageTimeLabel(message))} · ${esc(excerpt)}</p>${isSummaryOnly(message)?'<p class="helper">仅收到通知摘要，正文待核对。</p>':''}<button class="text-button" data-view="inbox" data-inbox-tab="messages">查看消息记录</button></div>`;
}
function renderToday(){
  const s=state.summary,active=state.tasks.filter(t=>!['submitted','cancelled'].includes(t.status)&&!['unverified','ambiguous','ended'].includes(t.checkin_verification));
  const unsubmitted=active.filter(t=>!isCalendarTaskOverdue(t)).length;
  const preview=state.proposals.slice(0,3).map(p=>{const c=p.candidate;return `<div class="review-preview">${pill(c.operation==='update'?'截止变更':c.deadline?'新任务':'截止未明确',c.operation==='update'?'green':'amber')}<h3>${esc(c.course||'课程待填写')} · ${esc(c.title)}</h3><p>${esc(p.before?formatDeadline(p.before.deadline)+' → '+formatDeadline(c.deadline):formatDeadline(c.deadline))}</p><button class="text-button" data-view="inbox">核对原文并确认 ↗</button></div>`}).join('');
  const platformReviews=state.tasks.filter(platformNeedsReview);
  const notices=platformReviews.map(t=>`<div class="review-preview"><h3>${esc(t.title)} · 平台状态待核对</h3><p>学习通：${esc(t.platform_check.status)}；本地：${esc(statusNames[t.status])}</p><button class="text-button" data-detail="${t.id}">核对提交状态 ↗</button></div>`).join('')+recentMessagePreview()+preview;
  content.innerHTML=intro('今日概览','课程消息有出处，截止时间不遗漏。')+
    `<section class="hero"><div><h2>${s.pending_reviews?s.pending_reviews+' 条草稿待确认':'还没有待确认草稿'}</h2></div><div class="hero-right"><button class="button primary" ${s.pending_reviews?'data-view="inbox"':'data-open-import'}>${s.pending_reviews?'打开收件箱':'导入通知'} <span>↗</span></button></div></section>
    <div class="stats-grid"><article class="stat"><div class="stat-top"><span>尚未提交</span><span class="stat-symbol" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="3"/><path d="m8 12 3 3 5-6"/></svg></span></div><div class="stat-number">${unsubmitted}<small>项任务</small></div></article><article class="stat"><div class="stat-top"><span>未来 7 天截止</span><span class="stat-symbol" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2"/></svg></span></div><div class="stat-number">${s.upcoming}<small>项任务</small></div></article><article class="stat ${s.overdue?'danger':''}"><div class="stat-top"><span>已经逾期</span><span class="stat-symbol" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></svg></span></div><div class="stat-number">${s.overdue}<small>项任务</small></div></article><article class="stat"><div class="stat-top"><span>已确认提交</span><span class="stat-symbol" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg></span></div><div class="stat-number">${s.submitted}<small>项任务</small></div><p class="stat-note">本地手动记录</p></article></div>
    <div class="two-columns"><section class="panel"><div class="panel-head"><div class="panel-title"><h2>待办任务</h2><small>${active.length}</small></div><button class="text-button" data-view="tasks">全部任务 ↗</button></div>${active.length?active.slice(0,4).map(priority).join(''):empty('待办还很清爽','导入真实通知，或用示例体验完整流程。','<button class="button primary" data-demo>加载示例数据</button>')}</section><section class="panel"><div class="panel-head"><div class="panel-title"><h2>最近收到的通知</h2><small>${state.messages.length}</small></div><button class="text-button" data-view="inbox">查看收件箱 ↗</button></div>${notices||empty('还没有待确认消息','新通知、延期和材料变更会出现在这里。')}</section></div>
    <div class="toolbar"><button class="text-button notification-button" data-notifications>开启浏览器截止提醒</button><span class="helper">仅在页面打开时提醒。</span></div>`;
}
function taskMatchesStatus(task,status,now){
  if(status==='all')return true;
  if(status==='active'&&['unverified','ambiguous','ended'].includes(task.checkin_verification))return false;
  if(status==='active')return !['submitted','cancelled'].includes(task.status)&&!isCalendarTaskOverdue(task,now);
  if(status==='overdue')return isCalendarTaskOverdue(task,now);
  return task.status===status;
}
function taskMatchesDeadline(task,period,now=new Date()){
  if(!period||period==='all')return true;
  if(period==='unknown')return !task.deadline;
  if(!task.deadline)return false;
  const date=task.deadline.length===10?task.deadline:cnLocalTime(new Date(task.deadline)).slice(0,10),today=cnLocalTime(now).slice(0,10);
  if(period==='today')return date===today;
  if(period==='week')return date>=today&&date<=cnLocalTime(new Date(now.getTime()+6*86400000)).slice(0,10);
  return period==='month'&&date.slice(0,7)===today.slice(0,7);
}
function deadlineInRange(value,from,to){
  if(!from&&!to)return true;
  if(!value)return false;
  const day=value.length===10?value:cnLocalTime(new Date(value)).slice(0,10);
  return (!from||day>=from)&&(!to||day<=to);
}
function filteredTasks(){
  const now=new Date();
  return state.tasks.filter(t=>(!filters.course||t.course===filters.course)&&(!filters.search||(t.title+t.course+t.scope).toLowerCase().includes(filters.search.toLowerCase()))&&taskMatchesStatus(t,filters.status,now)&&taskMatchesDeadline(t,filters.deadline,now)&&deadlineInRange(t.deadline,filters.deadlineFrom,filters.deadlineTo));
}
function platformNeedsReview(task){
  const c=task.platform_check;if(!c||!c.suggested_status||task.status==='cancelled')return false;
  if(c.suggested_status==='submitted')return task.status!=='submitted';
  return task.status==='submitted'||(['已退回','退回重做','待重交','需重交'].includes(c.status)&&['done','in_progress'].includes(task.status));
}
function platformCheckHTML(task){
  const check=task.platform_check;
  if(!check)return '';
  const stale=Date.now()-new Date(check.checked_at).getTime()>86400000;
  const changed=platformNeedsReview(task);
  const detailError=task.deadline?(check.detail_error||'').replace('作答时间未包含完整年份，截止时间请核对原文。',''):check.detail_error;
  return `<section class="platform-check"><p><strong>学习通状态：${esc(check.status||'未显示')}</strong></p>${stale?'<p class="helper">平台状态需重新同步。</p>':''}${detailError?`<p class="helper">${esc(detailError)}</p>`:''}${changed?`<p>${check.suggested_status==='submitted'?'平台显示已交，本地尚未记录。':'平台显示未交或需重交，请核对本地进度。'}</p>${!stale?`<button class="button small" data-adopt-platform="${esc(task.id)}" data-observation="${esc(check.observation_id)}" data-version="${task.version}">确认记为${esc(statusNames[check.suggested_status])}</button>`:''}`:''}</section>`;
}
function taskAttachmentLinksHTML(task){
  const links=new Map();
  for(const source of task.sources||[])for(const attachment of source.external?.attachments||[]){
    if(/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(attachment.url))links.set(attachment.url,attachment.name);
  }
  return links.size?`<details class="evidence"><summary>来源中的附件（${links.size}）</summary>${[...links].map(([url,name])=>`<p><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(name)} ↗</a></p>`).join('')}</details>`:'';
}
function taskRows(){
  const tasks=filteredTasks();
  if($('#taskResults'))$('#taskResults').textContent=`显示 ${tasks.length} / ${state.tasks.length} 项任务`;
  $('#taskRows').innerHTML=tasks.length?tasks.map(t=>{const due=dueLabel(t),overdue=isUnstartedOverdue(t);return `<article class="task-row"><span class="course-icon">${esc((t.course||'任务').slice(0,2))}</span><div class="task-body"><h3>${esc(t.title)}${platformNeedsReview(t)?' · 平台状态待核对':''}</h3><p><span>${esc(t.course||'课程待填写')}</span> · ${t.scope&&t.scope!==t.course?esc(t.scope)+' · ':''}${esc(kindNames[t.kind])} ${t.sample?'· 示例':''}</p>${t.platform_check?.status?`<span class="task-platform-status">学习通：${esc(t.platform_check.status)}</span>`:''}</div><div class="task-due">${overdue&&!['ended','unverified','ambiguous'].includes(t.checkin_verification)?'':pill(due.text,due.color)}${t.deadline?`<p>${esc(formatDeadline(t.deadline))}</p>`:''}</div><select class="task-status${overdue?' is-overdue':''}" data-status="${t.id}" aria-label="${esc(t.title)}状态">${taskOptions(t.status,t)}</select>${['cancelled','submitted'].includes(t.status)?`<button class="button small" data-restore-task="${esc(t.id)}" data-restore-status="${t.status}" data-version="${t.version}">${t.status==='submitted'?'撤销提交':'恢复任务'}</button>`:''}<button class="button small" data-detail="${t.id}">查看详情</button></article>`}).join(''):empty('没有符合条件的任务','修改筛选条件，或先从消息收件箱确认任务。');
}
function renderTasks(){
  const courses=[...new Set(state.tasks.map(t=>t.course).filter(Boolean))].sort();
  content.innerHTML=intro('待办任务','按截止时间整理；完成和提交分别记录。','TASKS & CHECKLISTS')+`<div class="toolbar"><input id="taskSearch" aria-label="搜索任务" placeholder="搜索任务、课程或班级…" value="${esc(filters.search)}"><select id="courseFilter" aria-label="课程筛选"><option value="">全部课程</option>${courses.map(c=>`<option ${c===filters.course?'selected':''} value="${esc(c)}">${esc(c)}</option>`).join('')}</select><select id="statusFilter" aria-label="状态筛选"><option value="active" ${filters.status==='active'?'selected':''}>尚未提交</option><option value="all" ${filters.status==='all'?'selected':''}>全部任务</option><option value="overdue" ${filters.status==='overdue'?'selected':''}>已逾期</option>${Object.entries(statusNames).filter(([k])=>!['pending','in_progress','cancelled'].includes(k)).map(([k,v])=>`<option value="${k}" ${filters.status===k?'selected':''}>${v}</option>`).join('')}</select><select id="deadlineFilter" aria-label="截止时间筛选">${[["all","全部截止时间"],["today","今天截止"],["week","未来7天"],["month","本月截止"],["unknown","截止未明确"]].map(([key,label])=>`<option value="${key}" ${filters.deadline===key?"selected":""}>${label}</option>`).join("")}</select></div><div class="deadline-query"><label class="field">截止起始日期<input type="date" id="taskDeadlineFrom" value="${esc(filters.deadlineFrom)}"></label><span class="date-range-separator">至</span><label class="field">截止结束日期<input type="date" id="taskDeadlineTo" value="${esc(filters.deadlineTo)}"></label><button class="button small" id="taskDeadlineSearch">查询</button><button class="text-button" id="taskDeadlineReset">重置日期</button></div><div class="task-results"><span id="taskResults" role="status" aria-live="polite"></span><span>按截止时间排列</span></div><section class="task-list" id="taskRows"></section><p class="helper">“已提交”为本地记录，不代表平台回执。</p>`;
  taskRows();
  $('#taskSearch').addEventListener('input',e=>{filters.search=e.target.value;taskRows()});
  $('#courseFilter').addEventListener('change',e=>{filters.course=e.target.value;taskRows()});
  $('#statusFilter').addEventListener('change',e=>{filters.status=e.target.value;taskRows()});
  $('#taskDeadlineSearch').addEventListener('click',()=>{
    const from=$('#taskDeadlineFrom'),to=$('#taskDeadlineTo');if(!from.reportValidity()||!to.reportValidity())return;
    if(from.value&&to.value&&from.value>to.value){toast('起始日期不能晚于结束日期',true);return}
    filters.deadlineFrom=from.value;filters.deadlineTo=to.value;filters.deadline='all';$('#deadlineFilter').value='all';taskRows();
  });
  $('#taskDeadlineReset').addEventListener('click',()=>{filters.deadline='all';$('#deadlineFilter').value='all';filters.deadlineFrom='';filters.deadlineTo='';$('#taskDeadlineFrom').value='';$('#taskDeadlineTo').value='';taskRows()});
  $('#deadlineFilter').addEventListener('change',e=>{filters.deadline=e.target.value;filters.deadlineFrom='';filters.deadlineTo='';$('#taskDeadlineFrom').value='';$('#taskDeadlineTo').value='';taskRows()});
}
function proposalEdits(card,strict=false){
  const fields={};for(const name of ['title','course','scope','kind','submission_method'])fields[name]=$(`[data-field="${name}"]`,card).value;
  const precision=$('[data-precision]',card).value,value=$('[data-field="deadline"]',card).value;
  if(strict&&precision!=='unknown'&&!value)throw new Error('请填写截止日期，或选择“未明确”。');
  fields.deadline=precision==='unknown'||!value?null:precision==='minute'?value+(value.length===16?':00':'')+'+08:00':value;
  const original=state.proposals.find(p=>p.id===card.dataset.proposal)?.candidate.deadline;
  if(precision==='minute'&&value.length===16&&original?.endsWith('+08:00')&&original.slice(0,16)===value)fields.deadline=original;
  fields.requirements=[...new Set($('[data-field="requirements"]',card).value.split('\n').map(x=>x.trim()).filter(Boolean))];
  return fields;
}
function normalizeTaskKeyPart(value){return String(value??'').toLowerCase().replace(/[\p{P}\p{S}\p{Z}_]+/gu,'')}
function matchingUpdateTask(fields){
  const key=['course','scope','title'].map(name=>normalizeTaskKeyPart(fields[name])).join('|');
  return state.tasks.find(task=>['course','scope','title'].map(name=>normalizeTaskKeyPart(task[name])).join('|')===key);
}
function proposalAction(p,fields,edited=false){
  if(p.checkin_unverified)return 'unverified_checkin';
  if(p.checkin_expired)return 'expired_checkin';
  if(p.checkin_ambiguous)return 'ambiguous_checkin';
  if(p.duplicate_review?.length&&!edited)return 'duplicate_review';
  const target=p.before||(p.candidate.operation==='update'?matchingUpdateTask(fields):null);
  if(!target)return p.candidate.operation==='update'?'unmatched_update':'create';
  if(p.candidate.operation==='cancel')return 'cancel';
  if(p.candidate.operation==='update')return p.candidate.deadline_change_requested&&!fields.deadline?'missing_deadline':'update';
  if((fields.deadline&&target.deadline&&fields.deadline!==target.deadline)||(fields.submission_method&&target.submission_method&&fields.submission_method!==target.submission_method)||fields.kind!==target.kind)return edited&&['link','merge'].includes(p.action)?'update':'conflict';
  return 'merge';
}
function syncProposalAction(card){
  const p=state.proposals.find(x=>x.id===card.dataset.proposal);if(!p)return;
  const fields=proposalEdits(card),target=p.before||(p.candidate.operation==='update'?matchingUpdateTask(fields):null);
  const action=proposalAction(p,fields,card.dataset.dirty==='true');
  const confirm=$('[data-confirm]:not([data-conflict-resolution])',card);
  if(confirm){confirm.disabled=['unmatched_update','missing_deadline','duplicate_review','expired_checkin','ambiguous_checkin','unverified_checkin'].includes(action);confirm.textContent={unverified_checkin:'等待核验签到',expired_checkin:'签到已结束',ambiguous_checkin:'先核对签到场次',create:'确认创建',duplicate_review:'先核对疑似重复',update:'确认变更',unmatched_update:'先匹配原任务',missing_deadline:'填写新截止日期',link:'关联来源',merge:p.supplement_update?'确认补充到原任务':'合并来源',conflict:'解决冲突',cancel:'确认取消'}[action]}
  const hint=$('[data-action-hint]',card),needsTarget=action==='unmatched_update',needsDeadline=action==='missing_deadline',manualMatch=action==='update'&&!p.before&&target;
  hint.hidden=!(needsTarget||needsDeadline||manualMatch||action!==p.action);
  hint.textContent=action==='unverified_checkin'?'签到详情尚未读到，请同步学习通后刷新草稿；核验前不能创建待办。':action==='expired_checkin'?'该场签到已经截止，不能创建待办；原文保留。':action==='ambiguous_checkin'?'签到场次或截止依据不唯一，请核对原活动。':needsTarget?'未匹配到原任务。请核对任务名称、课程和班级；匹配到现有任务后才能确认，不能新建作业。':needsDeadline?'这是截止时间变更，请填写新的截止日期后再确认。':manualMatch?`已匹配到现有任务，当前截止${formatDeadline(target.deadline)}；确认后更新为${formatDeadline(fields.deadline)}并保留历史。`:action==='update'?'本次编辑将更新已有任务；按变更校验并保留历史。':action==='conflict'?'编辑后仍存在字段冲突，请在冲突处理中明确选择。':'本次将合并补充要求并关联原消息来源。';
}
function deadlineReferencesHTML(references){
  if(!references?.length)return '';
  return `<div class="warning deadline-references"><strong>其他通知中有截止时间，请核对</strong>${references.map(ref=>`<p>${esc(formatDeadline(ref.deadline))}${ref.status==='dismissed'?'（已忽略通知）':''} <button class="text-button" data-message-detail="${esc(ref.message_id)}">查看原文</button></p>`).join('')}</div>`;
}
function relativeDeadlineHTML(c){
  const r=c.relative_deadline;
  if(!r)return '';
  if(r.status==='already_applied')return `<p class="helper relative-deadline-summary">此次延期已核对，不再重复累加。当前截止：${esc(formatDeadline(c.deadline))}</p>`;
  if(r.status==='resolved'){
    const minutes=r.delta_minutes,amount=minutes%10080===0?minutes/10080+'周':minutes%1440===0?minutes/1440+'天':minutes%60===0?minutes/60+'小时':minutes+'分钟';
    return `<p class="helper relative-deadline-summary">延期计算：${esc(formatDeadline(r.base_deadline))} ＋ ${esc(amount)} → ${esc(formatDeadline(r.deadline))}</p>`;
  }
  return Array.isArray(r.options)&&r.options.length?`<details class="evidence relative-deadline-options"><summary>核对原任务（${r.options.length}）</summary>${r.options.map(t=>`<div class="toolbar"><span>${esc(t.title)} · ${esc(formatDeadline(t.deadline))}</span><button class="text-button" data-detail="${esc(t.task_id)}">查看任务</button></div>`).join('')}</details>`:'';
}
function proposalCard(p){
  const c=p.candidate,label={create:'新任务',update:'截止 / 材料变更',link:'重复任务 · 关联来源',merge:p.supplement_update?'补充原任务 · 待确认':'重复任务 · 合并来源',conflict:'字段冲突 · 待处理',cancel:'取消任务'}[p.action];
  const sourceMessage=state.messages.find(m=>m.id===p.message_id);
  const locked=p.target_id?'disabled':'';
  const initialAction=proposalAction(p,c);
  const precision=c.date_precision==='minute'?'minute':c.date_precision==='date'?'date':'unknown';
  const duplicateDetails=p.duplicate_review?.length?`<div class="warning duplicate-review"><strong>疑似重复，先核对已有任务</strong><p>请先核对已有任务；“仅关联原文”不会修改截止和进度。</p>${p.duplicate_review.map(item=>`<div class="toolbar"><span>${esc(item.course)} · ${esc(item.title)}</span><button class="button small" data-detail="${item.task_id}">查看已有任务</button>${item.reason==='conflicting_identity'?'<span>已有来源编号冲突，需要先核对原文。</span>':`<button class="button small" data-link-proposal="${p.id}" data-link-task="${item.task_id}" data-link-version="${item.version}">仅关联原文</button>`}</div>`).join('')}</div>`:'';
  const sourceDetails=(p.source_count||1)>1?`<details class="evidence proposal-source-group"><summary>${p.supplement_update?'原通知与补充记录（'+p.source_count+'）':'已合并 '+p.source_count+' 份相同候选来源'}</summary><div class="toolbar">${(p.source_message_ids||[p.message_id]).map((id,index)=>`<button class="button small" data-message-detail="${id}">查看来源 ${index+1}</button>`).join('')}</div></details>`:'';
  const conflictDetails=p.action==='conflict'?`<div class="warning conflict-warning"><strong>字段冲突</strong>${Object.entries(p.conflicts||{}).map(([name,value])=>`<p>${esc({deadline:'截止时间',submission_method:'提交方式',kind:'任务类型'}[name]||name)}：当前“${esc(name==='deadline'?formatDeadline(value.current):value.current)}”，新消息“${esc(name==='deadline'?formatDeadline(value.incoming):value.incoming)}”</p>`).join('')}</div>`:'';
  return `<article class="proposal-card" data-proposal="${p.id}"><div class="proposal-heading"><div>${pill(c.operation==='update'?'延期 · 待确认':label,p.action==='cancel'?'red':p.action==='update'?'green':p.action==='conflict'?'red':'amber')}${c.matchable?'':pill('名称需核对','outline')}${sourceMessage&&(sourceMessage.sample||isCompanionDemo(sourceMessage))?pill('示例','outline'):''}<h3>${esc(c.course||'未识别课程')} · ${esc(c.title)}</h3><p class="source-line">${esc(sourceMessage?messageSourceLabel(sourceMessage):'原始通知')} · 发布时间：${esc(c.published_at?dateLabel(c.published_at):(Object.prototype.hasOwnProperty.call(c,'published_at')?'未获取':sourceMessage?messageTimeLabel(sourceMessage):'未获取'))}</p></div></div>
  ${p.before?`<div class="change-box"><span>当前任务</span><span class="old">${esc(formatDeadline(p.before.deadline))}</span><span>→</span><strong>${esc(p.action==='cancel'?'确认后取消':formatDeadline(c.deadline||p.before.deadline))}</strong></div>`:''}
  ${duplicateDetails}${sourceDetails}${conflictDetails}${relativeDeadlineHTML(c)}${deadlineReferencesHTML(p.deadline_references)}${p.checkin_unverified?'<p class="warning">签到详情尚未核验，请同步学习通后刷新草稿；暂不创建待办。</p>':p.checkin_expired?'<p class="warning">该场签到已截止，不能创建待办；可忽略此草稿，原消息会保留。</p>':p.checkin_ambiguous?'<p class="warning">匹配到多个签到活动，请核对场次，不能按同名签到合并。</p>':''}<div class="proposal-grid"><label class="field">任务名称<input data-field="title" value="${esc(c.title)}" maxlength="160" ${locked}></label><label class="field">课程<input data-field="course" value="${esc(c.course)}" maxlength="100" ${locked}></label><label class="field">班级 / 分组<input data-field="scope" value="${esc(c.scope)}" maxlength="100" ${locked}></label><label class="field deadline-field">截止时间（北京时间）<div class="deadline-control"><select data-precision><option value="unknown" ${precision==='unknown'?'selected':''}>未明确</option><option value="date" ${precision==='date'?'selected':''}>日期</option><option value="minute" ${precision==='minute'?'selected':''}>时刻</option></select><input data-field="deadline" type="${precision==='minute'?'datetime-local':'date'}" value="${c.deadline?esc(precision==='minute'?c.deadline.slice(0,16):c.deadline.slice(0,10)):''}" ${precision==='unknown'?'disabled':''}></div></label><label class="field">类型<select data-field="kind">${Object.entries(kindNames).map(([k,v])=>`<option value="${k}" ${c.kind===k?'selected':''}>${v}</option>`).join('')}</select></label><label class="field">提交方式<input data-field="submission_method" value="${esc(c.submission_method||'')}" maxlength="160" placeholder="例如：学习通上传、课堂展示"></label></div>
  <label class="field">任务要求（每行一项）<textarea data-field="requirements" rows="${Math.min(8,Math.max(4,c.requirements.length+1))}">${esc(c.requirements.join('\n'))}</textarea></label>
  ${Array.isArray(c.model_review)&&c.model_review.length?`<details class="evidence model-review"><summary>规则 / 模型分歧（${c.model_review.length}）· 请核对</summary>${c.model_review.map(r=>`<p><strong>${esc({deadline:'截止时间',submission_method:'提交方式',kind:'类型',operation:'操作'}[r.field]||r.field)}</strong>：规则 ${esc(r.field==='deadline'?formatDeadline(r.rule):r.rule)} → 模型 ${esc(r.field==='deadline'?formatDeadline(r.model):r.model)}</p><p>模型依据：${esc(r.evidence||'未提供')}；${esc(r.resolution==='evidence_corrected'?'草稿已按原文截止修正，确认后生效':'暂保留规则值，可在上方字段修改后确认')}</p>`).join('')}</details>`:''}
  ${c.warnings.length?`<div class="warning">${c.warnings.map(w=>`<p>△ ${esc(w)}</p>`).join('')}</div>`:''}
  <details class="evidence"><summary>查看消息原文与提取依据</summary><pre>${esc(state.messages.find(m=>m.id===p.message_id)?.text||c.evidence)}</pre><p>原文日期依据：${esc(c.deadline_evidence||'未识别')}。${c.teacher?'教师：'+esc(c.teacher)+'。':''}${c.platform_status?'平台状态：'+esc(c.platform_status)+'（仅作证据）。':''}${p.target_id?'已有任务的名称、课程和班级不能在此更改；需重新导入以重新匹配。':''}</p>${c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener noreferrer">打开学习通原任务 ↗</a>`:''}</details><p class="error-text proposal-error" role="alert"></p>
  <p class="helper" data-action-hint ${initialAction==='unmatched_update'||initialAction==='missing_deadline'?'':'hidden'}>${initialAction==='unmatched_update'?'未匹配到原任务。请核对任务名称、课程和班级；匹配到现有任务后才能确认，不能新建作业。':initialAction==='missing_deadline'?'这是截止时间变更，请填写新的截止日期后再确认。':''}</p><div class="proposal-actions"><button class="button subtle" data-reanalyze-message="${p.message_id}">刷新草稿</button><button class="button subtle" data-dismiss="${p.id}">忽略草稿</button>${p.action==='conflict'?`<button class="button" data-confirm="${p.id}" data-conflict-resolution="current">保留当前并关联来源</button><button class="button primary" data-confirm="${p.id}" data-conflict-resolution="incoming">采用新消息</button>`:`<button class="button primary" data-confirm="${p.id}" ${['unmatched_update','missing_deadline','duplicate_review','expired_checkin','ambiguous_checkin','unverified_checkin'].includes(initialAction)?'disabled':''}>${{unverified_checkin:'等待核验签到',expired_checkin:'签到已结束',ambiguous_checkin:'先核对签到场次',create:'确认创建',duplicate_review:'先核对疑似重复',update:'确认变更',unmatched_update:'先匹配原任务',missing_deadline:'填写新截止日期',link:'关联来源',merge:p.supplement_update?'确认补充到原任务':'合并来源',conflict:'解决冲突',cancel:'确认取消'}[initialAction]}</button>`}</div></article>`;
}
function renderInbox(){
  const conflicts=state.proposals.filter(p=>p.action==='conflict'),pending=state.proposals.filter(p=>p.action!=='conflict'),archived=state.archived_proposals||[];
  const tabs=[['pending','待确认草稿',pending.length],['conflicts','冲突处理',conflicts.length],['messages','消息记录',state.message_total??state.messages.length],['archived','历史归档',archived.length]];
  content.innerHTML=intro('消息收件箱','核对新任务与变更，确认后加入待办。','MESSAGE INBOX')+`<button class="text-button" data-view="sync">同步学习通消息 ↗</button><div class="section-tabs">${tabs.map(([key,label,count])=>`<button class="section-tab ${inboxTab===key?'active':''}" data-inbox-tab="${key}">${label} ${count}</button>`).join('')}</div><div id="inboxBody"></div>`;
  const body=$('#inboxBody');
  if(inboxTab==='pending')body.innerHTML=pending.length?pending.map(proposalCard).join(''):empty('待确认区已经清空','新通知进入这里，确认后会出现在待办中。','<button class="button primary" data-open-import>导入通知</button>');
  else if(inboxTab==='conflicts')body.innerHTML=conflicts.length?conflicts.map(proposalCard).join(''):empty('没有待处理冲突','同一任务出现不同截止或提交方式时会进入冲突列表。');
  else if(inboxTab==='messages'){
    body.innerHTML=`<div class="deadline-query"><label class="field">截止起始日期<input type="date" id="messageDeadlineFrom" value="${esc(messageDeadlineFilters.from)}"></label><span class="date-range-separator">至</span><label class="field">截止结束日期<input type="date" id="messageDeadlineTo" value="${esc(messageDeadlineFilters.to)}"></label><button class="button small" id="messageDeadlineSearch">查询</button><button class="text-button" id="messageDeadlineReset">重置日期</button></div><div id="messageList"><div class="loading">正在读取消息…</div></div>`;
    $('#messageDeadlineSearch').addEventListener('click',()=>{
      const from=$('#messageDeadlineFrom'),to=$('#messageDeadlineTo');if(!from.reportValidity()||!to.reportValidity())return;
      if(from.value&&to.value&&from.value>to.value){toast('起始日期不能晚于结束日期',true);return}
      messageDeadlineFilters.from=from.value;messageDeadlineFilters.to=to.value;loadMessagePage(0).catch(error=>toast(error.message,true));
    });
    $('#messageDeadlineReset').addEventListener('click',()=>{messageDeadlineFilters.from='';messageDeadlineFilters.to='';$('#messageDeadlineFrom').value='';$('#messageDeadlineTo').value='';loadMessagePage(0).catch(error=>toast(error.message,true))});
    loadMessagePage(messagePageOffset).catch(error=>toast(error.message,true));
  }else if(inboxTab==='archived'){
    const reasons={deadline_passed:'首次接收时截止已过',task_ended:'任务已结束',already_submitted:'平台显示已提交或已完成',reminder_only:'已有作业的倒计时或状态提醒，不新增任务'};
    body.innerHTML='<p class="helper">历史任务与系统提醒保留在此，可恢复核对。</p>'+(archived.length?archived.map(p=>`<article class="message-card"><h3>${esc(p.candidate.title)}</h3><p>${esc(p.candidate.course||'课程待核对')} · ${esc(reasons[p.archive_reason]||'历史任务')}</p><p class="helper">${esc(formatDeadline(p.candidate.deadline))}</p><div class="toolbar"><button class="button small" data-message-detail="${p.message_id}">查看原文</button><button class="text-button" data-reanalyze-message="${p.message_id}">恢复并重新核对</button></div></article>`).join(''):empty('没有历史归档任务','明确过期或结束的自动采集任务会保留在这里。'));
  }
}
function messageCard(message){
  const ext=message.external||{},body=ext.kind==='task_center'?[ext.title,ext.description,ext.platform_status?'平台状态：'+ext.platform_status:''].filter(Boolean).join('\n'):message.text;
  return `<article class="message-card" data-message-id="${message.id}"><div class="message-heading"><label class="message-select"><input type="checkbox" data-message-select="${message.id}" aria-label="选择这条消息"><strong>${esc(messageSourceLabel(message))}</strong></label><div class="message-times"><span class="message-published">发布时间：${esc(messageTimeLabel(message))}</span><span class="message-deadline">截止时间：${esc(messageDeadlineLabel(message))}</span></div></div><div class="priority-meta">${message.scope?pill(message.scope,'outline'):''}${message.sample||isCompanionDemo(message)?pill('示例','amber'):''}</div><pre>${esc(body)}</pre>${summaryHelp(message)}${message.trace?.length?traceHTML(message.trace):''}<div class="message-actions"><button class="button primary small" data-message-detail="${message.id}">查看消息详情</button><button class="button small" data-reanalyze-message="${message.id}">按规则重新提取</button></div></article>`;
}
async function loadMessagePage(offset=0){
  const request=++messagePageRequest;
  const query=new URLSearchParams({limit:MESSAGE_PAGE_SIZE,offset});
  const filtered=!!(messageDeadlineFilters.from||messageDeadlineFilters.to);
  if(messageDeadlineFilters.from)query.set('deadline_from',messageDeadlineFilters.from);
  if(messageDeadlineFilters.to)query.set('deadline_to',messageDeadlineFilters.to);
  const page=await json('/api/messages/page?'+query);
  if(request!==messagePageRequest||view!=='inbox'||inboxTab!=='messages'||!$('#messageList'))return;
  if(!page.items.length&&offset>0&&page.total)return loadMessagePage(Math.floor((page.total-1)/MESSAGE_PAGE_SIZE)*MESSAGE_PAGE_SIZE);
  messagePage=page;messagePageOffset=page.offset;selectedMessages.clear();
  $('#messageList').innerHTML=`<div class="toolbar message-tools"><label class="message-select"><input id="selectPageMessages" type="checkbox" ${page.items.length?'':'disabled'}>选择本页</label><button class="button small" id="clearSelectedMessages" disabled>清理所选消息</button><button class="button subtle small" id="clearAllMessages" ${filtered?'hidden':''} ${page.total?'':'disabled'}>清理全部消息</button></div>`+(page.items.length?page.items.map(messageCard).join(''):(filtered?empty('没有符合截止日期的消息','调整日期范围，或重置日期查看全部消息。'):empty('还没有导入消息','文本、截图和学习通消息可以进入收件箱。')))+`<div class="toolbar message-pagination"><span class="helper">共 ${page.total} 条 · 第 ${Math.floor(page.offset/MESSAGE_PAGE_SIZE)+1} / ${Math.max(1,Math.ceil(page.total/MESSAGE_PAGE_SIZE))} 页</span><button class="button small" id="messagesPrevious" ${page.offset?'':'disabled'}>上一页</button><button class="button small" id="messagesNext" ${page.offset+page.items.length<page.total?'':'disabled'}>下一页</button></div>`;
  $('[data-inbox-tab="messages"]').textContent='消息记录 '+(page.unfiltered_total??state.message_total??page.total);
}
function syncMessageSelection(){
  const button=$('#clearSelectedMessages'),all=$('#selectPageMessages');
  if(button){button.disabled=!selectedMessages.size;button.textContent=selectedMessages.size?'清理所选 '+selectedMessages.size+' 条':'清理所选消息'}
  if(all){all.checked=!!messagePage.items.length&&selectedMessages.size===messagePage.items.length;all.indeterminate=selectedMessages.size>0&&!all.checked}
}
async function prepareCleanup(all=false){
  const snapshot=all?await json('/api/messages/cleanup-preview'):{ids:[...selectedMessages]};
  cleanupIds=[...snapshot.ids];
  if(!cleanupIds.length){toast('没有待清理消息');return}
  $('#cleanupDescription').textContent=`将从消息列表清理 ${cleanupIds.length} 条消息。`+(snapshot.total>cleanupIds.length?'本轮最多清理 10000 条。':'')+'确认期间收到的新消息会保留。';
  $('#cleanupDialog').showModal();
}
function renderCalendar(){
  clearInterval(calendarClockTimer);calendarClockTimer=null;
  const year=month.getFullYear(),mn=month.getMonth();
  const today=cnLocalTime().slice(0,10),cells=[];
  const anchorDay=Math.min(Number(today.slice(8,10)),new Date(year,mn+1,0).getDate());
  const start=new Date(year,mn,anchorDay);
  start.setDate(start.getDate()-(start.getDay()+6)%7-14);
  for(let i=0;i<35;i++){
    const d=new Date(start.getFullYear(),start.getMonth(),start.getDate()+i);const stamp=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    const tasks=state.tasks.filter(t=>t.deadline?.slice(0,10)===stamp&&t.status!=='cancelled');
    const hasOverdue=tasks.some(t=>isCalendarTaskOverdue(t));
    cells.push(`<div class="day ${stamp===today?'today':''} ${d.getMonth()!==mn?'other-month':''} ${hasOverdue?'has-overdue':''}"><span class="day-number">${d.getDate()}</span>${tasks.map(t=>{const overdue=isCalendarTaskOverdue(t);return `<button class="calendar-task ${t.status==='submitted'?'submitted':''} ${overdue?'overdue':''}" data-detail="${t.id}" title="${esc(t.course+' · '+t.title+' / '+formatDeadline(t.deadline)+(overdue?' / 已逾期':''))}">${esc(t.course+' · '+t.title)}${overdue?'<span class="calendar-overdue-label">已逾期</span>':''}</button>`}).join('')}</div>`);
  }
  content.innerHTML=intro('截止日历','统一查看课程任务，导出到你常用的手机或电脑日历。','DEADLINE CALENDAR')+`<div class="calendar-toolbar"><div class="calendar-controls"><button class="button small" data-month="-1" aria-label="上个月">‹</button><h2>${year} 年 ${mn+1} 月</h2><button class="button small" data-month="1" aria-label="下个月">›</button><button class="text-button" data-month="0">本月</button></div><div class="calendar-current"><span>当前时间</span><time id="calendarNow"></time></div><button id="exportCalendar" class="button primary" data-download="calendar">↓ 导出日历</button></div><section class="calendar">${['周一','周二','周三','周四','周五','周六','周日'].map(d=>`<div class="weekday">${d}</div>`).join('')}${cells.join('')}</section><details class="calendar-help"><summary>日历说明</summary><p>红色为逾期，灰色为已提交；已取消任务不显示。</p><p>导出时，明确时刻的任务提前 2 小时提醒；未明确时刻的任务按全天事件处理。</p></details>`;
  calendarRenderedDate=today;updateCalendarClock();calendarClockTimer=setInterval(()=>{if(view!=='calendar'){clearInterval(calendarClockTimer);calendarClockTimer=null;return}const currentDate=cnLocalTime().slice(0,10);if(currentDate!==calendarRenderedDate){if(month.getFullYear()===Number(calendarRenderedDate.slice(0,4))&&month.getMonth()===Number(calendarRenderedDate.slice(5,7))-1)month=new Date(currentDate+'T12:00:00');renderCalendar()}else updateCalendarClock()},1000);
}
function webBridgePanel(standalone=false){
  const body=`<p>自动同步学习通网页版的课程通知、聊天文字及已打开的作业考试中心条目，无需手机伴侣。</p><div class="toolbar"><a class="button primary" href="/downloads/courseinbox-browser-companion.zip" download>下载浏览器组件 0.3.0</a><a class="button" href="https://i.chaoxing.com/" target="_blank" rel="noopener noreferrer">打开学习通官网 ↗</a></div><label class="field">网页同步令牌<div class="pair-row"><input id="webPairToken" type="password" class="pair-input" readonly placeholder="用于浏览器组件"><button id="webTokenReveal" class="button small">显示</button><button id="webTokenCopy" class="button small">复制</button></div></label><ol class="step-list"><li>在 Edge / Chrome 扩展管理页开启开发者模式，加载解压后的组件文件夹；旧版组件更新后点击重新加载。</li><li>打开组件，粘贴此令牌，启用同步并保存。</li><li>登录学习通官网，打开收件箱、作业或考试中心页面。聊天文字从“消息”中的当前会话同步。</li></ol><p class="helper">约每分钟检查课程通知；作业考试中心读取当前页面已显示的条目。任务说明附件会尝试读取；任务仍须确认后才加入待办。</p>`;
  return standalone?`<section class="panel">${body}</section>`:`<details class="connection-option"><summary>学习通网页同步</summary><div class="option-body">${body}</div></details>`;
}
let desktopStatusTimer,desktopQrURL='',desktopStatusLoading=false;
let taskInventoryOffset=0,taskInventorySignature='',taskInventoryRepairRunning=false,taskInventoryAttentionOnly=true,taskInventorySnapshot=null,taskInventoryRepairNotice=null;
function paintInventoryRepair(report){
  const output=$('#taskInventoryRepairStatus');if(!output)return;
  if(taskInventoryRepairRunning){output.hidden=false;output.textContent='正在提交补收请求…';return}
  const notice=taskInventoryRepairNotice;if(!notice)return;
  output.hidden=false;
  if(!notice.count){output.textContent='当前没有可自动补收的缺失项。';return}
  if(notice.completed){output.textContent='本次补收已读取，请到收件箱核对草稿；任务不会自动确认。';return}
  const rows=notice.sections?report?.sections:report?.items;
  const matches=notice.keys.map(key=>(rows||[]).find(item=>item.key===key));
  const refreshed=matches.length===notice.count&&matches.every(item=>item?.checked_at&&item.checked_at!==notice.before.get(item.key));
  const complete=refreshed&&matches.every(item=>notice.sections?item.state==='checked':!['missing','unrecognized'].includes(item.state)&&item.detail_state==='read');
  if(complete)notice.completed=true;
  output.textContent=complete?'本次补收已读取，请到收件箱核对草稿；任务不会自动确认。':refreshed?'本轮检查已返回，仍有内容待补读或核对。':report?.enabled===false?'补收等待恢复同步。':`已安排 ${notice.count} ${notice.sections?'个栏目检查':'项补收'}，等待后台读取；结果自动刷新。`;
}
function renderTaskInventory(report){
  const panel=$('#taskInventory');if(!panel)return;
  taskInventorySnapshot=report;paintInventoryRepair(report);
  const signature=JSON.stringify(report);if(signature===taskInventorySignature)return;taskInventorySignature=signature;
  const names={missing:'未保存',unrecognized:'已保存，未识别',pending:'待确认',confirmed:'已关联任务',archived:'历史归档',ignored:'已忽略',cleared:'已清理'};
  const counts=report.counts||{};
  $('#taskInventorySummary').textContent=`待处理 ${report.attention_count??((counts.missing||0)+(counts.unrecognized||0)+(counts.pending||0))} 项`;
  $('#taskInventoryCounts').textContent=Object.entries({missing:'未保存',unrecognized:'未识别',pending:'待确认',confirmed:'已关联',ignored:'已忽略'}).filter(([key])=>counts[key]>0).map(([key,label])=>label+' '+counts[key]).join(' · ');
  $('#taskInventoryScope').textContent=taskInventoryAttentionOnly?'查看全部来源':'仅看待处理';
  const coverage=[];
  if(!report.catalog_at&&!report.sections?.length)coverage.push('尚未取得平台清单，请恢复同步');
  if(report.unchecked_sections)coverage.push(`${report.unchecked_sections} 个栏目待检查`);
  const detailPending=report.attention_detail_pending??report.detail_pending??0,manualDetails=report.attention_manual_details??report.manual_details??0;
  if(detailPending)coverage.push(`详情待补读 ${detailPending} 项`);
  if(manualDetails)coverage.push(`详情或附件需核对 ${manualDetails} 项`);
  const deadlinePending=report.attention_deadline_pending??report.deadline_pending??0;
  if(deadlinePending)coverage.push(`截止时间待核对 ${deadlinePending} 项`);
  if(report.catalog_limited)coverage.push('课程入口仍有覆盖缺口');
  if(!report.enabled)coverage.push('同步已暂停，显示上次记录');
  $('#taskInventoryCoverage').textContent=coverage.join(' · ');$('#taskInventoryCoverage').hidden=!coverage.length;
  const sectionNames={unchecked:'尚未检查',partial:'列表未读完整',failed:'读取失败',checked:'列表已核对'};
  const reasons={timeout:'加载超时',dom:'页面结构或入口未识别',http_5xx:'平台暂时异常',http_error:'页面请求失败',expired:'登录已失效',identity:'任务身份不完整或不匹配',unavailable:'暂未读取成功'};
  $('#taskInventorySections').innerHTML=(report.sections||[]).map(section=>`<li>${esc(section.course)} · ${section.kind==='exam'?'考试':'作业'}：${sectionNames[section.state]||'待核对'}${section.freshness!=='fresh'?'（待重新验证）':''}${section.reason?' · '+esc(reasons[section.reason]||'需核对'):''}${section.unidentified_count?' · 身份未核对 '+Number(section.unidentified_count)+' 项':''}${section.checked_at?' · 上次检查 '+esc(dateLabel(section.checked_at)):''}${report.enabled&&(section.state!=='checked'||section.freshness!=='fresh')?` <button class="text-button" data-inventory-section="${esc(section.key)}">重试此栏目</button>`:''}</li>`).join('')||'<li>等待课程列表。</li>';
  $('#taskInventoryList').innerHTML=(report.items||[]).map(item=>{
    const canRepair=report.enabled&&!['cleared','ignored','archived'].includes(item.state)&&(['missing','unrecognized'].includes(item.state)||item.detail_state==='pending');
    const detail=item.detail_state==='pending'?'正文待补读':item.detail_state==='manual'?'正文需人工核对':'正文已读取';
    const manual=item.manual_supplement?`<p class="helper">人工补充：${esc({pending:'待确认',confirmed:'已确认补充',dismissed:'已忽略草稿',unrecognized:'已保存，尚未识别任务'}[item.manual_supplement.status]||'已保存')}${item.manual_supplement.file_partial?' · 补充文件仍需核对':''}；自动读取状态保留。</p>`:'';
    return `<article class="inventory-task"><div><strong>${esc(item.title)}</strong><p class="helper">${esc(item.course)} · ${item.kind==='exam'?'考试':'作业'} · ${names[item.state]||'待核对'}</p><p class="helper" title="${esc(item.detail_error||'')}">${detail}${item.deadline_conflict?' · 截止时间有冲突':item.deadline_pending?' · 截止时间待核对':''}${item.media_pending?' · 附件或图片未读全':''}${item.detail_error&&!item.deadline_pending&&!item.media_pending?' · '+esc(item.detail_error):''}</p>${manual}</div><div class="toolbar">${item.message_id?`<button class="button small" data-message-detail="${esc(item.message_id)}">查看原文</button><button class="button small" data-supplement="${esc(item.message_id)}">补充详情</button>`:''}${canRepair?`<button class="button small" data-inventory-repair="${esc(item.key)}">补收此项</button>`:''}</div></article>`;
  }).join('')||(taskInventoryAttentionOnly?'<div class="inventory-empty"><strong>暂无待处理项目</strong><p>这里显示当前已检查来源中需要核对的任务。</p></div>':'<p class="helper">暂无来源记录。</p>');
  const pages=Math.max(1,Math.ceil((report.total||0)/20));
  $('.inventory-pagination').hidden=pages<=1;
  $('#taskInventoryPagination').textContent=`第 ${Math.floor((report.offset||0)/20)+1} / ${pages} 页 · 每页20项`;
  $('#taskInventoryPrevious').disabled=!report.offset;$('#taskInventoryNext').disabled=(report.offset||0)+20>=(report.total||0);
  const repair=$('#taskInventoryRepair');
  repair.disabled=taskInventoryRepairRunning||!report.enabled||!((counts.missing||0)+(counts.unrecognized||0)+(report.attention_detail_pending??report.detail_pending??0));
  repair.title=taskInventoryRepairRunning?'正在安排补收':!report.enabled?'请先恢复同步':repair.disabled?'暂无可自动补收的缺失项':'补收缺失项';
  repair.setAttribute('aria-busy',String(taskInventoryRepairRunning));
  repair.textContent=taskInventoryRepairRunning?'正在安排补收…':'补收缺失项';
}
const desktopStateNames={idle:'尚未连接',connecting:'正在连接学习通…',waiting_scan:'等待扫码确认',connected:'后台同步已开启',syncing:'正在读取学习通消息…',expired:'需要重新扫码',paused:'同步已暂停',error:'连接需要处理',retrying:'网络波动，正在重试',partial:'部分消息待重试'};
async function loadDesktopStatus(){
  if(view!=='sync'||desktopStatusLoading)return;desktopStatusLoading=true;
  try{
    const offset=taskInventoryOffset;
    const [result,settingsResult,inventory]=await Promise.all([json('/api/chaoxing/desktop/status'),json('/api/settings'),json('/api/chaoxing/desktop/inventory?limit=20&offset='+offset+'&scope='+(taskInventoryAttentionOnly?'attention':'all'))]);if(view!=='sync')return;
    if(offset===taskInventoryOffset){taskInventoryOffset=inventory.offset||0;renderTaskInventory(inventory)}
    const counts=settingsResult.chaoxing_web||{};
    const health=$('#desktopHealth');
    if(health)health.textContent=result.freshness==='stale'?'进度较久未更新，后台正在恢复；可立即重新检查。':result.freshness==='offline'?'后台进程已停止，正在等待自动恢复。':result.restart_count?'后台已自动恢复 '+result.restart_count+' 次。':'';
    if($('#desktopRecheck'))$('#desktopRecheck').hidden=!result.session_saved;
    $('#desktopState').textContent=desktopStateNames[result.state]||'连接需要处理';
    $('.desktop-sync-panel').dataset.state=result.state||'error';
    const completed=result.sources?.notice?.last_complete_success||result.sources?.notice?.last_success;
    $('#desktopLastComplete').textContent=completed?dateLabel(completed):'尚无完整检查记录';
    $('#desktopLastMessage').textContent=result.last_received?dateLabel(result.last_received):'尚未收到消息';
    $('#desktopError').textContent=result.last_error||(result.queued?`有 ${result.queued} 条消息等待补传。`:'');
    const latest=[];if(result.last_checked)latest.push('最近检查：'+dateLabel(result.last_checked));if(result.last_received)latest.push('最近收到：'+dateLabel(result.last_received));$('#desktopTimeline').textContent=latest.join(' · ');
    const manual=Object.values(result.sources||{}).some(source=>source.media_pending_count>0||source.attachment_pending_count>0||source.unsupported_detail_count>0);
    const hints={idle:'扫码连接后，新消息会自动进入收件箱。',connecting:'正在连接，请稍候。',waiting_scan:'请用学习通 App 扫码，并在手机上确认。',connected:'新消息会自动进入收件箱，任务仍需确认。',syncing:'正在后台检查新消息。',expired:'登录已过期，请重新扫码。',paused:'恢复后继续接收新消息。',error:'连接暂时不可用，请重试；仍失败时可重新扫码。',retrying:'正在自动重试，已保存的消息可正常查看。',partial:manual?'部分内容未读完整，请查看原文核对；支持的内容会继续重试。':'正在重试未读内容，已保存的消息可正常查看。'};
    $('#desktopLatest').textContent=result.session_saved&&!['expired','paused'].includes(result.state)&&['stale','offline'].includes(result.freshness)?'同步进度暂未更新，后台正在恢复。'+(manual?'部分内容仍需核对。':''):hints[result.state]||'请查看同步详情，核对连接状态。';
    const sourceNames={idle:'尚未连接',connecting:'连接中',syncing:'读取中',connected:'已同步',retrying:'待重试',partial:'部分待重试',expired:'需重新扫码',error:'需处理'};
    const stageNames={detail_content:'通知正文待重试',detail_parse:'通知正文结构待核对',chat_content:'聊天内容待重试',chat_conversation:'聊天会话待重试',task_navigation:'课程入口待重试',task_list:'作业/考试列表待重试'};
    $('#desktopSources').textContent=['chat','notice','task_center'].map(name=>{const source=result.sources?.[name]||{},details=[];if(source.pending_count>0)details.push('待检查/重试 '+source.pending_count);if(source.issue_summary)details.push(source.issue_summary);if(source.checked_count>0)details.push('本轮读取 '+(source.captured_count||0)+'/'+source.checked_count);if(source.failed_count>0)details.push('本轮未读 '+source.failed_count);if(source.detail_pending_count>0)details.push('详情待补读 '+source.detail_pending_count);if(source.unsupported_detail_count>0)details.push('详情入口需人工核对 '+source.unsupported_detail_count);if(source.media_pending_count>0)details.push('图片或媒体待核对 '+source.media_pending_count);if(source.attachment_pending_count>0)details.push('附件内容未读完整 '+source.attachment_pending_count);if(source.coverage==='loaded_text')details.push('范围：已加载的聊天文字');if(source.coverage==='list_only')details.push('范围：列表信息');if(source.freshness==='stale')details.push('进度较久未更新');if(stageNames[source.stage])details.push(stageNames[source.stage]);if(source.last_complete_success||source.last_success)details.push('上次完整检查 '+dateLabel(source.last_complete_success||source.last_success));else if(source.last_checked)details.push('检查 '+dateLabel(source.last_checked));return ({chat:'聊天',notice:'课程通知',task_center:'作业/考试'}[name])+'：'+(!result.enabled?'已暂停':sourceNames[source.state]||'连接中')+(details.length?'（'+details.join(' · ')+'）':'')}).join(' · ');
    $('#desktopCounts').textContent=`已保存 ${counts.received_count||0} 条 · 聊天 ${counts.chat_count||0} · 课程通知 ${counts.course_notice_count||0} · 作业/考试 ${counts.task_center_count||0}`;
    const retryable=result.enabled&&result.session_saved&&['retrying','partial','error'].includes(result.state);
    const requiresLogin=!result.session_saved||result.qr_ready||['expired','connecting','waiting_scan'].includes(result.state);
    $('#desktopPause').hidden=!result.enabled;$('#desktopResume').hidden=requiresLogin||(result.enabled&&!retryable);
    $('#desktopResume').textContent=result.enabled?'重试连接':'恢复同步';$('#desktopResume').classList.toggle('primary',!requiresLogin);
    $('#desktopLogin').classList.toggle('primary',requiresLogin);
    const primary=$('#desktopPrimary'),more=$('#desktopAccountActions');
    primary.insertBefore($('#desktopPause'),primary.querySelector('[data-view="inbox"]'));
    for(const [button,main] of [[$('#desktopLogin'),requiresLogin],[$('#desktopRecheck'),!requiresLogin&&result.enabled&&!retryable]]){
      const parent=main?primary:more;if(button.parentElement!==parent)parent.prepend(button);
    }
    $('#desktopRecheck').classList.toggle('primary',!requiresLogin&&result.enabled&&!retryable);
    $('#desktopLogin').textContent=(result.session_saved||result.qr_ready||result.state==='expired')?'重新扫码登录':'扫码连接学习通';
    $('#desktopLogin').disabled=result.state==='connecting';
    $('#desktopLogin').setAttribute('aria-busy',String(result.state==='connecting'));
    if(result.state==='connecting')$('#desktopLogin').textContent='正在连接…';
    $('#desktopLogout').hidden=!result.session_saved;
    $('#desktopQRPanel').hidden=!result.qr_ready;
    if(result.qr_ready){
      const response=await api('/api/chaoxing/desktop/qr');const blob=await response.blob();if(view!=='sync')return;
      if(desktopQrURL)URL.revokeObjectURL(desktopQrURL);desktopQrURL=URL.createObjectURL(blob);$('#desktopQR').src=desktopQrURL;
    }else if(desktopQrURL){URL.revokeObjectURL(desktopQrURL);desktopQrURL='';$('#desktopQR').removeAttribute('src')}
  }catch(error){if(view==='sync'&&$('#desktopError')){$('#desktopError').textContent=error.message;$('#desktopState').textContent='连接状态暂不可用';$('#desktopLatest').textContent='状态暂时无法更新，请稍后重试。'}}
  finally{desktopStatusLoading=false}
}
async function renderWebSync(){
  clearInterval(desktopStatusTimer);
  content.innerHTML=intro('学习通后台同步','首次扫码连接，之后在后台接收新消息。','')+`<section class="panel desktop-sync-panel">
    <div class="connect-heading"><span class="connect-number sync-indicator" aria-hidden="true">↻</span><div><h2 id="desktopState">正在读取连接状态…</h2><p class="helper" id="desktopLatest"></p></div></div>
    <div class="sync-overview"><div><span>通知完整检查</span><strong id="desktopLastComplete">读取中…</strong></div><div><span>最近收到消息</span><strong id="desktopLastMessage">读取中…</strong></div></div><div class="toolbar" id="desktopPrimary"><button class="button primary" id="desktopLogin">扫码连接学习通</button><button class="button" id="desktopResume" hidden>恢复同步</button><button class="button" id="desktopRecheck" hidden>立即同步</button><button class="text-button" data-view="inbox" data-inbox-tab="messages">查看收到的消息 ↗</button></div>
    <div id="desktopQRPanel" class="desktop-qr" hidden><img id="desktopQR" alt="学习通官方登录二维码"><p>用学习通 App 扫码，并在 App 中确认登录。</p><p class="helper">二维码失效时点击“重新扫码登录”。</p></div>
    <details id="desktopOptions" class="sync-options"><summary>账号与诊断</summary>
      <div class="toolbar" id="desktopAccountActions"><button class="button" id="desktopPause" hidden>暂停同步</button><button class="button subtle" data-download="acceptance">导出检查报告</button><button class="button" id="desktopLoginWindow">打开首次登录窗口</button><button class="button subtle" id="desktopLogout" hidden>退出账号并清除本机登录</button></div>
      <details id="desktopDiagnostics" class="sync-diagnostics"><summary>同步详情</summary><p id="desktopTimeline" class="helper"></p><p id="desktopSources" class="helper"></p><p id="desktopCounts" class="helper"></p><p id="desktopError" class="desktop-sync-error"></p><p id="desktopHealth" class="helper"></p></details>
      <p class="helper sync-account-note">登录状态仅保存在本机；退出账号不会删除已接收的消息和任务。</p>
    </details>
  </section><details class="connection-option" style="margin-top:20px"><summary>其他同步方式</summary>${webBridgePanel(true)}</details>`;
  taskInventoryOffset=0;taskInventorySignature='';taskInventorySnapshot=null;taskInventoryRepairNotice=null;
  $('.desktop-sync-panel').insertAdjacentHTML('afterend','<section class="panel" id="taskInventory"><h2>任务核对与补收</h2><p class="helper">补齐遗漏，确认后加入待办。</p><p id="taskInventorySummary" role="status">正在读取核对清单…</p><p class="helper" id="taskInventoryCoverage"></p><p id="taskInventoryRepairStatus" class="inventory-repair-status" role="status" aria-live="polite" hidden></p><div class="toolbar"><button class="button" id="taskInventoryRepair" disabled>补收缺失项</button><button class="button subtle" id="taskInventoryRefresh">刷新核对结果</button><button class="text-button" id="taskInventoryScope">查看全部来源</button></div><details><summary>查看各课程检查情况</summary><p id="taskInventoryCounts" class="helper"></p><ul id="taskInventorySections" class="inventory-sections"></ul></details><div id="taskInventoryList"></div><div class="toolbar inventory-pagination"><button class="button small" id="taskInventoryPrevious" disabled>上一页</button><span id="taskInventoryPagination" class="helper"></span><button class="button small" id="taskInventoryNext" disabled>下一页</button></div></section>');
  await loadDesktopStatus();desktopStatusTimer=setInterval(()=>{if(view==='sync')loadDesktopStatus();else clearInterval(desktopStatusTimer)},3000);
}

function messageTimeLabel(message){
  if(message.timing)return message.timing.published_at?dateLabel(message.timing.published_at).trim()+(message.timing.publication_source==='notice'?'（发布通知）':''):'未获取';
  if(message.external?.kind==='task_center')return message.external.published_at?dateLabel(message.external.published_at).trim():'未获取';
  return message.external?.time_known===false?'未获取':dateLabel(message.captured_at).trim();
}
function messageDeadlineLabel(message){
  const value=message.timing?.deadline||message.external?.deadline;
  if(!value)return '未获取';
  const source=message.timing?.deadline_source;
  return formatDeadline(value)+(source==='confirmed_task'?'（已确认任务）':source==='candidate'?'（待核对）':'');
}
function mobileRemindersPanel(){
  return `<section id="mobileReminders" class="panel mobile-reminders" aria-labelledby="mobileRemindersTitle">
    <div class="reminder-heading"><div><h2 id="mobileRemindersTitle">接收电脑提醒</h2><p class="helper">手机与电脑连接同一 Wi-Fi，无需安装应用。</p></div><button id="mobileRemindersToggle" class="button primary" disabled>读取中…</button></div>
    <p id="mobileRemindersStatus" class="reminder-status" role="status">正在读取提醒服务状态…</p><p id="mobileRemindersError" class="connection-warning" role="status" hidden></p>
    <div class="reminder-setup"><div><h3>1. 用手机浏览器打开地址</h3><div id="mobileRemindersAddresses" class="reminder-addresses">开启后显示地址。</div></div>
    <div><h3>2. 输入配对码</h3><div class="reminder-pair-row"><output id="mobileRemindersCode" class="reminder-code" aria-label="手机提醒配对码">尚未生成</output><button id="mobileRemindersPair" class="button" disabled>生成配对码</button></div><p id="mobileRemindersExpiry" class="helper">5 分钟有效，仅限一次。</p></div></div>
    <p class="helper reminder-network-help">电脑保持运行，手机网页保持打开；锁屏或切到后台可能暂停提醒。</p>
    <details class="connection-option"><summary>连接不上？</summary><div class="option-body"><p>确认两台设备在同一 Wi-Fi，避免使用隔离设备的访客网络。检查 Windows 防火墙是否允许 TCP 8766。</p></div></details>
    <div class="reminder-device-heading"><h3>已配对手机</h3><span class="helper">撤销后需重新配对</span></div><div id="mobileRemindersDevices" class="reminder-devices"><p class="helper">正在读取设备…</p></div>
  </section>`;
}
let wechatPushStatus=null,wechatPushBusy=false;
function wechatPushPanel(){
  return `<section class="panel" id="wechatPush"><h2>微信推送</h2><p class="helper">通过 pushplus 接收提醒，无需手机打开网页。电脑需保持运行；消息摘要会发送至第三方服务。</p><label class="field">pushplus Token<input id="wechatPushToken" type="password" autocomplete="off" spellcheck="false" maxlength="256" placeholder="在本机填写，不必发送到聊天"></label><label class="check"><input id="wechatPushEnabled" type="checkbox"> 开启微信推送</label><div class="toolbar"><button type="button" class="button primary" id="wechatPushSave">保存设置</button><button type="button" class="button" id="wechatPushTest" disabled>发送测试</button><button type="button" class="button subtle" id="wechatPushClear" disabled>清除 Token</button><a class="text-button" href="https://www.pushplus.plus/" target="_blank" rel="noopener noreferrer">获取 Token ↗</a></div><p id="wechatPushStatus" class="helper" role="status">正在读取设置…</p><p id="wechatPushResult" class="helper" role="status"></p><p id="wechatPushError" class="error-text" role="alert"></p><p class="helper">首次开启不补发历史消息。任务仅发送标题和截止摘要，普通消息仅提示有新消息；接口受理不等于微信已送达。</p></section>`;
}
function paintWechatPush(){
  if(view!=='mobile'||!$('#wechatPush')||!wechatPushStatus)return;
  const s=wechatPushStatus;
  $('#wechatPushStatus').textContent=!s.configured?'尚未配置 Token':s.paused?'自动发送已暂停；检查配置后保存以恢复':s.enabled?'微信推送已开启':'微信推送已关闭';
  $('#wechatPushToken').placeholder=s.configured?'Token 已加密保存；留空则保留':'填写 pushplus 用户或消息 Token';
  for(const name of ['Save','Test','Clear'])$('#wechatPush'+name).disabled=wechatPushBusy||name==='Test'&&(!s.enabled||!s.configured)||name==='Clear'&&!s.configured;
  const labels={none:'暂无发送记录',accepted:'pushplus 已受理，微信送达尚未确认',failed:'发送失败',unknown:'发送结果不明，请核对微信；未自动重发',retry:'等待限次重试',sending:'发送中或结果待确认'};
  $('#wechatPushResult').textContent=(labels[s.last_result]||'状态待核对')+(s.last_at?' · '+dateLabel(s.last_at):'')+(s.receipt?' · 流水号：'+s.receipt:'')+(s.last_error?'；'+s.last_error:'');
}
async function loadWechatPushStatus(generation){
  if(wechatPushBusy)return;
  const before=wechatPushStatus;
  const result=await json('/api/wechat-push/status');
  if(view!=='mobile'||generation!==mobileRemindersGeneration||wechatPushBusy||before!==wechatPushStatus)return;
  const first=!wechatPushStatus;wechatPushStatus=result;
  if(first)$('#wechatPushEnabled').checked=result.enabled;
  paintWechatPush();
}
async function changeWechatPush(button){
  if(wechatPushBusy)return;
  wechatPushBusy=true;paintWechatPush();$('#wechatPushError').textContent='';
  try{
    let result;
    if(button.id==='wechatPushTest'){
      if($('#wechatPushToken').value.trim()||$('#wechatPushEnabled').checked!==wechatPushStatus.enabled)throw new Error('请先保存设置，再发送测试。');
      result=await json('/api/wechat-push/test',{method:'POST',body:{}});
    }
    else{
      const token=$('#wechatPushToken').value.trim(),body=button.id==='wechatPushClear'?{enabled:false,clear_token:true}:{enabled:$('#wechatPushEnabled').checked,...(token?{token}:{})};
      result=await json('/api/wechat-push/settings',{method:'POST',body});
    }
    wechatPushStatus=result;
    if(view==='mobile'&&$('#wechatPush')){$('#wechatPushToken').value='';$('#wechatPushEnabled').checked=result.enabled;}
  }catch(error){if(view==='mobile'&&$('#wechatPushError'))$('#wechatPushError').textContent=error.message;}
  finally{wechatPushBusy=false;paintWechatPush();}
}
function paintMobileRemindersStatus(){
  if(view!=='mobile'||!$('#mobileReminders'))return;
  const status=mobileRemindersStatus,toggle=$('#mobileRemindersToggle'),pair=$('#mobileRemindersPair');
  toggle.disabled=mobileRemindersBusy||!status;pair.disabled=mobileRemindersBusy||!status?.enabled||!status?.listening;
  toggle.setAttribute('aria-busy',String(mobileRemindersBusy));
  pair.title=mobileRemindersBusy?'请等待当前操作完成':!status?'尚未读取提醒状态':!status.enabled?'请先开启电脑提醒':!status.listening?'提醒服务尚未开始监听':'';
  if(!status)return;
  toggle.textContent=mobileRemindersBusy?'处理中…':status.enabled?'关闭电脑提醒':'开启电脑提醒';
  $('#mobileRemindersStatus').textContent=status.enabled?(status.listening?'提醒已开启':'正在启动提醒服务'):'提醒已关闭';
  $('#mobileRemindersAddresses').innerHTML=status.enabled?(status.addresses?.length?status.addresses.map(address=>/^http:\/\/(?:\d{1,3}\.){3}\d{1,3}:\d+$/.test(address)?`<div class="reminder-address"><a href="${esc(address)}/" target="_blank" rel="noopener noreferrer">${esc(address)}/</a><button class="button small" data-reminder-copy-address="${esc(address)}/">复制地址</button></div>`:`<code>${esc(address)}</code>`).join(''):'未找到可用局域网地址，请检查电脑的 Wi-Fi 连接。'):'开启提醒后显示电脑地址。';
  const pushOrigin=status.web_push?.origin;
  if(status.enabled&&/^https:\/\/[a-zA-Z0-9.-]+$/.test(pushOrigin||''))$('#mobileRemindersAddresses').insertAdjacentHTML('afterbegin',`<div class="reminder-address"><a href="${esc(pushOrigin)}/" target="_blank" rel="noopener noreferrer">后台通知：${esc(pushOrigin)}/</a><button class="button small" data-reminder-copy-address="${esc(pushOrigin)}/">复制地址</button></div>`);
  const networkHelp=$('.reminder-network-help');if(networkHelp)networkHelp.textContent=pushOrigin?'用 HTTPS 地址配对并开启后台提醒后，可以关闭手机页面；电脑需保持运行。':'局域网页面需保持前台；运行“启动手机后台提醒.cmd”可准备 HTTPS 后台通知入口。';
  $('#mobileRemindersDevices').innerHTML=status.devices?.length?status.devices.map(device=>`<div class="reminder-device"><div><strong>${esc(device.name||'未命名手机')}</strong><p class="helper">${device.web_push?'后台提醒已开启':device.online?'在线':'离线'} · 最近连接：${esc(device.last_seen?dateLabel(device.last_seen):'尚未连接')}</p></div><button class="button small" data-reminder-revoke="${esc(device.id)}" ${mobileRemindersBusy||!status.enabled?'disabled':''}>撤销</button></div>`).join(''):'<p class="helper">暂无已配对手机。</p>';
  if(!status.enabled){$('#mobileRemindersCode').textContent='尚未生成';$('#mobileRemindersExpiry').textContent='5 分钟有效，仅限一次。'}
}
function mobileRemindersError(message=''){
  if(view!=='mobile'||!$('#mobileRemindersError'))return;
  $('#mobileRemindersError').textContent=message;$('#mobileRemindersError').hidden=!message;
}
async function loadMobileRemindersStatus(generation=mobileRemindersGeneration){
  if(view!=='mobile'||generation!==mobileRemindersGeneration)return;
  let request=mobileRemindersRequest;
  try{
    if(!mobileRemindersBusy){request=++mobileRemindersRequest;const status=await json('/api/mobile-reminders/status');if(view!=='mobile'||generation!==mobileRemindersGeneration||request!==mobileRemindersRequest)return;mobileRemindersStatus=status;paintMobileRemindersStatus();mobileRemindersError(status.error||'')}
    await loadWechatPushStatus(generation);
  }catch(error){if(generation===mobileRemindersGeneration&&request===mobileRemindersRequest)mobileRemindersError(error.message)}
  finally{if(view==='mobile'&&generation===mobileRemindersGeneration){clearTimeout(mobileRemindersTimer);mobileRemindersTimer=setTimeout(()=>loadMobileRemindersStatus(generation),5000)}}
}
async function changeMobileReminders(button){
  if(mobileRemindersBusy||!mobileRemindersStatus)return;
  const generation=mobileRemindersGeneration,status=mobileRemindersStatus;
  mobileRemindersBusy=true;mobileRemindersRequest++;paintMobileRemindersStatus();mobileRemindersError();
  try{
    if(button.id==='mobileRemindersToggle'){
      const next=await json('/api/mobile-reminders/settings',{method:'POST',body:{enabled:!status.enabled}});
      if(generation!==mobileRemindersGeneration)return;mobileRemindersStatus=next;mobileRemindersError(next.error||'');
    }else if(button.id==='mobileRemindersPair'){
      if(!status.enabled||!status.listening)return;
      const pairing=await json('/api/mobile-reminders/pairing',{method:'POST',body:{}});
      if(view!=='mobile'||generation!==mobileRemindersGeneration)return;
      $('#mobileRemindersCode').textContent=pairing.code;$('#mobileRemindersExpiry').textContent='有效期至 '+dateLabel(pairing.expires_at)+' · 仅可使用一次';
    }else if(button.hasAttribute('data-reminder-revoke')){
      if(!status.enabled)return;
      await json('/api/mobile-reminders/revoke',{method:'POST',body:{id:button.dataset.reminderRevoke}});
      const next=await json('/api/mobile-reminders/status');if(generation!==mobileRemindersGeneration)return;mobileRemindersStatus=next;mobileRemindersError(next.error||'');
    }
  }catch(error){if(generation===mobileRemindersGeneration)mobileRemindersError(error.message)}
  finally{mobileRemindersBusy=false;if(generation===mobileRemindersGeneration)paintMobileRemindersStatus()}
}
async function renderMobile(){
  wechatPushStatus=null;
  clearTimeout(mobileRemindersTimer);const generation=++mobileRemindersGeneration;
  content.innerHTML=intro('连接手机','电脑采集学习通，手机接收提醒。','')+'<div class="loading">正在读取配对信息…</div>';
  try{
    settings=await json('/api/settings');
    if(view!=='mobile'||generation!==mobileRemindersGeneration)return;
    const discovery=settings.mobile_discovery||{};
    const lan=settings.addresses.find(a=>/^192\.168\.|^10\.|^172\.(1[6-9]|2\d|3[01])\./.test(a));
    const endpoint=lan?'http://'+lan+':'+settings.server_port:'';
    const localOnly=settings.listen_host!=='0.0.0.0';
    content.innerHTML=intro('连接手机','电脑采集学习通，手机接收提醒。','')+`<div class="mobile-connect">
      ${wechatPushPanel()}<details class="connection-options browser-reminder-options"><summary>备用：手机网页连接</summary><div class="connection-options-body">${mobileRemindersPanel()}</div></details>
      <details class="connection-options legacy-mobile-options"><summary>手机 App 上传通知（可选）</summary><div class="connection-options-body">
      ${localOnly?'<div class="connection-warning" role="status">仅在使用下方“手机 → 电脑”上传时，需要用 <code>start-lan.cmd</code> 启动。上方电脑提醒可直接开启。</div>':''}
      <section class="connect-download panel"><span class="connect-number" aria-hidden="true">1</span><div><h2>安装手机应用</h2><p>Android 8.0 及以上 · <a href="/downloads/courseinbox-learning-0.3.20-arm64-debug.apk" download>64位精简版</a></p></div><a class="button primary" href="/downloads/courseinbox-learning-0.3.20-debug.apk" download>下载安装包</a></section>
      <section class="panel connect-panel"><div class="connect-heading"><span class="connect-number" aria-hidden="true">2</span><div><h2>让手机连接这台电脑</h2><p class="helper">在手机点击“连接电脑”，填写下面的信息。</p></div><span class="connection-state">${localOnly?'仅本机可访问':'局域网模式'}</span></div>
        <label class="field">电脑名称<div class="pair-row"><input id="pairComputer" class="pair-input" readonly value="${esc(discovery.name||'')}" placeholder="尚未生成"><button class="button small" data-copy-field="pairComputer">复制</button></div></label>
        <label class="field">配对令牌<div class="pair-row"><input id="pairToken" class="pair-input" type="password" readonly placeholder="点击复制，粘贴到手机"><button id="tokenReveal" class="button small">显示</button><button id="tokenCopy" class="button small">复制</button></div></label>
        <label class="field">电脑地址<span class="helper">自动寻找失败时填写</span><div class="pair-row"><input id="pairAddress" class="pair-input" readonly value="${esc(endpoint)}" placeholder="未找到局域网地址"><button class="button small" data-copy-field="pairAddress">复制</button></div></label>
        ${!discovery.available?'<p class="helper connection-fallback">自动发现暂不可用，请在手机填写电脑地址。</p>':''}
      </section>
      <section class="panel connect-finish"><div class="connect-heading"><span class="connect-number" aria-hidden="true">3</span><div><h2>开启通知权限</h2><p class="helper">在手机系统设置中允许通知访问，然后返回伴侣。</p></div></div><div class="connect-finish-row"><p>新通知会尝试自动同步，也可在手机点击“同步一次”。</p><button class="button" data-mobile-messages>查看收到的消息 ↗</button></div></section>
      </div></details>
      <details class="connection-options"><summary>更多连接选项</summary><div class="connection-options-body">
        <details class="connection-option"><summary>调整接收应用</summary><div class="option-body"><label class="field">应用包名<textarea id="packageList" rows="2">${esc(settings.allowed_packages.join('\n'))}</textarea><span class="helper">每行一个；手机“设置 → 同步范围”需填写相同包名。</span></label><button id="savePackages" class="button small">保存接收应用</button></div></details>
        ${webBridgePanel()}
        <details class="connection-option"><summary>连接遇到问题</summary><div class="option-body"><p>手机与电脑需在可互通的网络，电脑服务保持运行。找不到电脑时，填写上面的电脑地址再连接。</p><p class="helper">${esc(discovery.reason||'自动发现不可用时可手动填写地址。')}</p><p>通知只有摘要时，请补充原文或截图。</p></div></details>
      </div></details>
    </div>`;
    await loadMobileRemindersStatus(generation);
  }catch(error){toast(error.message,true)}
}
function renderView(){
  content.dataset.page=view;
  content.classList.toggle('today-page',view==='today');
  content.classList.toggle('tasks-page',view==='tasks');
  if(view!=='evaluation')window.CourseInboxEvaluation?.unmount();
  if(view!=='mobile'){clearTimeout(mobileRemindersTimer);mobileRemindersTimer=null;mobileRemindersGeneration++}
  if(view!=='calendar'&&calendarClockTimer){clearInterval(calendarClockTimer);calendarClockTimer=null}
  document.querySelectorAll('.sidebar [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  ({today:renderToday,tasks:renderTasks,inbox:renderInbox,calendar:renderCalendar,mobile:renderMobile,sync:renderWebSync,evaluation:()=>window.CourseInboxEvaluation.mount(content,{json,api,esc,toast,intro,isActive:()=>view==='evaluation'})}[view]||renderToday)();
}
function showView(next){
  if(!['today','tasks','inbox','calendar','mobile','sync','evaluation'].includes(next))return;
  view=next;history.replaceState(null,'','#'+next);renderView();window.scrollTo({top:0});
}
async function saveDetail(changes){
  const id=detailId;
  const previous=state.tasks.find(task=>task.id===id)?.status;
  document.querySelectorAll('#taskDetail input,#taskDetail select').forEach(i=>i.disabled=true);
  try{
    const updated=await json('/api/tasks/'+id,{method:'PATCH',body:{...changes,expected_version:Number($('#taskDetail').dataset.version)}});
    await refresh();
    if($('#taskDialog').open && detailId===id)await openTask(id);
    if(['cancelled','submitted'].includes(changes.status)&&previous!==changes.status)taskStatusSaved(updated,previous);
  }catch(error){
    toast(error.message,true);
    if($('#taskDialog').open && detailId===id)await openTask(id);
  }finally{document.querySelectorAll('#taskDetail input,#taskDetail select').forEach(i=>i.disabled=false)}
}
async function openTask(id){
  detailId=id;
  const task=await json('/api/tasks/'+id);
  if(detailId!==id)return;
  const overdue=isCalendarTaskOverdue(task),unstartedOverdue=isUnstartedOverdue(task);
  $('#detailTitle').textContent=task.title;
  $('#taskDetail').innerHTML=`<div class="detail-meta">${pill(task.course||'课程未填写','green')}${task.scope&&task.scope!==task.course?pill(task.scope,'outline'):''}${pill(kindNames[task.kind])}${task.sample?pill('示例','amber'):''}${overdue&&!unstartedOverdue?pill('已逾期','red'):''}</div><p class="due-meta">截止：${esc(formatDeadline(task.deadline))}</p>${task.submission_method?`<p>提交方式：${esc(task.submission_method)}</p>`:''}${task.teacher?`<p>教师：${esc(task.teacher)}</p>`:''}${!task.platform_check&&task.platform_status?`<p>学习通状态：${esc(task.platform_status)}（仅作证据）</p>`:''}${task.source_url?`<p><a href="${esc(task.source_url)}" target="_blank" rel="noopener noreferrer">打开学习通原任务 ↗</a></p>`:''}<h3>任务要求</h3><textarea class="task-requirements" aria-label="任务要求" rows="6" readonly>${esc(task.checklist.length?task.checklist.map(x=>x.text).join('\n'):'原文未明确要求。')}</textarea>${taskAttachmentsHTML(task.sources)}<label class="field">任务状态<select id="detailStatus" data-detail-status="${task.id}">${taskOptions(task.status,task)}</select></label>${task.status==='done'?'<p class="detail-status-note">已做完，记得在原平台提交</p>':'<p class="helper">本地进度，不影响原平台。</p>'}<details class="evidence"><summary>消息来源（${task.sources.length}）</summary>${task.sources.map(m=>`<p>${esc(messageSourceLabel(m))} · ${esc(messageTimeLabel(m))}</p><pre>${esc(m.text)}</pre><button class="text-button" data-message-detail="${esc(m.id)}">查看消息详情 ↗</button>`).join('')}</details><details class="evidence"><summary>变更历史（${task.history.length}）</summary>${task.history.map(h=>`<div class="detail-history"><strong>${esc(dateLabel(h.at))} · ${esc({create:'创建任务',update:'确认变更',link:'关联来源',merge:'合并来源',merge_older_source:'关联较早来源',duplicate_task_merged:'合并重复任务',duplicate_source_linked:'核对重复并关联原文',conflict_keep_current:'冲突：保留当前',conflict_use_incoming:'冲突：采用新消息',cancel:'取消任务',reminder_misclassification_corrected:'纠正为系统提醒',deadline_misclassification_corrected:'纠正误识别日期',platform_status_confirmed:'确认采用平台状态','status/checklist':'状态或材料更新'}[h.action]||h.action)}</strong>${esc(h.before?formatDeadline(h.before.deadline)+' → '+formatDeadline(h.after.deadline):formatDeadline(h.after.deadline))}<br>状态：${esc(statusNames[h.after.status])}</div>`).join('')}</details>`;
  $('#taskDetail').dataset.version=task.version;
  $('#taskDetail').dataset.status=task.status;
  $('#detailStatus').classList.toggle('is-overdue',unstartedOverdue);
  if(['cancelled','submitted'].includes(task.status))$('#detailStatus').closest('.field').insertAdjacentHTML('afterend',`<button class="button" data-restore-task="${esc(task.id)}" data-restore-status="${task.status}" data-version="${task.version}">${task.status==='submitted'?'撤销提交':'恢复任务'}</button>`);
  $('#taskDetail').insertAdjacentHTML('afterbegin',platformCheckHTML(task));
  if(task.checkin_verification&&task.checkin_verification!=='verified'&&!['submitted','cancelled'].includes(task.status))$('#taskDetail').insertAdjacentHTML('afterbegin',`<p class="warning">${task.checkin_verification==='ended'?'该场签到已结束，已停止待办提醒。':'签到详情待核验，暂不列入有效待办和提醒。'}原任务和本地进度保留。</p>`);
  $('#taskDetail .due-meta').insertAdjacentHTML('beforebegin',`<p class="published-meta">发布时间：${esc(task.published_at?dateLabel(task.published_at):'未获取')}</p>`);
  $('#taskDetail').insertAdjacentHTML('afterbegin',deadlineReferencesHTML(task.deadline_references));
  $('#taskDetail').insertAdjacentHTML('beforeend',taskAttachmentLinksHTML(task));
  const supplementSource=task.sources.find(message=>!message.supplement);
  if(supplementSource&&!task.excluded_reason)$('#taskDetail').insertAdjacentHTML('beforeend',`<div class="toolbar"><button class="button" data-supplement="${esc(supplementSource.id)}" data-supplement-target="task:${esc(task.id)}">补充详情</button></div>`);
  if(task.excluded_reason==='reminder_only'){
    $('#taskDetail').insertAdjacentHTML('afterbegin','<p class="connection-warning">这条记录已纠正为系统提醒，不再列为任务。原文与纠正历史保留。</p>');
    $('#taskDetail').querySelectorAll('input,select').forEach(input=>input.disabled=true);
  }
  if(!$('#taskDialog').open)$('#taskDialog').showModal();
}
function messageLink(url,label){
  if(typeof url!=='string'||!/^https?:\/\//i.test(url))return '';
  try{const parsed=new URL(url);if(parsed.username||parsed.password)return ''}catch{return ''}
  return `<a class="text-button" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
}
function taskAttachmentsHTML(sources){
  const files=new Map();
  for(const message of sources)for(const [index,attachment] of (message.external?.attachments||[]).entries()){
    const key=attachment.url||attachment.name;
    if(!files.has(key))files.set(key,{...attachment,...(message.external?.kind==='task_center'?{source_message_id:message.id,source_attachment_index:index}:{})});
  }
  return messageAttachmentsHTML([...files.values()],'taskAttachments');
}
function attachmentDownloadHTML(attachment,index,sourceId){
  const messageId=attachment.source_message_id||sourceId,position=attachment.source_attachment_index??index;
  if(messageId&&/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(attachment.url||''))return `<button class="text-button" data-attachment-download="/api/messages/${esc(messageId)}/attachments/${position}/download" data-attachment-name="${esc(attachment.name)}">下载附件</button>`;
  return messageLink(attachment.url,'打开原附件');
}
async function downloadAttachment(button){
  const response=await fetch(button.dataset.attachmentDownload,{headers:{Authorization:'Bearer '+token}});
  if(!response.ok){const error=await response.json();throw Error(error.error||'附件下载失败，请重试。')}
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=button.dataset.attachmentName||'attachment';document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
}
function messageAttachmentsHTML(attachments,sectionId='messageAttachments',sourceId=''){
  if(!attachments?.length)return '';
  return `<section id="${sectionId}" class="message-section"><h3>附件 <span class="helper">${attachments.length} 个</span></h3>${attachments.map((a,index)=>`<article class="message-attachment"><div class="message-attachment-heading"><strong>${esc(a.name||'未命名附件')}</strong>${pill(a.status==='skipped'&&a.url&&a.error?.startsWith('原文件已关联')?'原文件已关联':{extracted:'文字已读取',partial:'仅读取部分文字',failed:'读取失败',skipped:'尚未读取',listed:'尚未读取'}[a.status]||'尚未读取',a.status==='extracted'?'green':'amber')}</div>${attachmentDownloadHTML(a,index,sourceId)}${a.error?`<p class="helper">${esc(a.error)}</p>`:''}${a.text?`<details class="evidence"><summary>查看附件文字</summary><pre class="message-detail-text">${esc(a.text)}</pre></details>`:''}</article>`).join('')}</section>`;
}
function messageRelatedHTML(related={}){
  const tasks=related.tasks||[],proposals=related.proposals||[];
  if(!tasks.length&&!proposals.length)return '<section id="messageRelated" class="message-section"><p class="helper">尚无关联任务或草稿。</p></section>';
  return `<section id="messageRelated" class="message-section"><h3>关联任务与草稿</h3>${tasks.map(t=>`<article class="message-related-row"><div><strong>${esc(t.title)}</strong><p class="helper">${esc(t.course||'课程待填写')} · ${esc(formatDeadline(t.deadline))}</p>${pill('已确认任务','green')}${pill(statusNames[t.status]||t.status,'outline')}</div><button class="button small" data-detail="${esc(t.id)}">查看任务</button></article>`).join('')}${proposals.map(p=>`<article class="message-related-row"><div><strong>${esc(p.title)}</strong><p class="helper">${esc(p.course||'课程待填写')} · ${esc(formatDeadline(p.deadline))}</p>${pill(p.status==='pending'?(p.action==='conflict'?'冲突待确认':'待确认草稿'):p.status==='archived'?'已归档草稿':'已忽略草稿',p.status==='pending'?'amber':'outline')}</div>${p.status==='pending'?`<button class="button small" data-message-proposal="${esc(p.id)}">核对草稿</button>`:''}</article>`).join('')}</section>`;
}
function messageReadStatus(message){
  const meta=message.external||{},attachments=meta.attachments||[],notes=[];
  let title='已接收的消息内容';
  if(isSummaryOnly(message)){title='正文尚未接收';notes.push('当前只有系统通知摘要，请打开原平台核对，或补充完整内容。')}
  else if(meta.kind==='task_center'&&meta.detail_state!=='read'){title='任务说明待核对';notes.push(meta.detail_error||'当前保存了列表信息，尚未读到完整任务说明。')}
  if(attachments.some(a=>a.status!=='extracted'))notes.push('部分附件文字尚未读全，请核对原附件。');
  if(meta.media_pending_count)notes.push(`还有 ${meta.media_pending_count} 项图片或媒体内容待核对。`);
  if(meta.kind==='course_notice'&&meta.notice_body_state==='empty')notes.push('原通知正文为空，已保存标题和来源。');
  if(meta.extraction_warning)notes.push(meta.extraction_warning);
  if(message.supplement?.file_partial)notes.push('补充文件仅读取部分文字，请核对原文件。');
  if(notes.length&&title==='已接收的消息内容')title='已接收文字，部分内容待核对';
  return `<div id="messageReadStatus" class="message-read-status ${notes.length?'needs-review':''}" role="status"><strong>${esc(title)}</strong>${notes.length?`<p>${notes.map(esc).join(' ')}</p>`:''}</div>`;
}
async function openMessage(id){
  const generation=++messageDetailGeneration,dialog=$('#messageDialog'),detail=$('#messageDetail');
  detailId=null;
  if($('#taskDialog').open)$('#taskDialog').close();
  messageDetailCurrent=null;detail.dataset.messageId=id;detail.innerHTML='<div class="loading" role="status">正在读取消息详情…</div>';
  if(!dialog.open)dialog.showModal();
  const current=()=>generation===messageDetailGeneration&&dialog.open&&detail.dataset.messageId===id;
  try{
    const message=await json('/api/messages/'+id);
    if(!current())return;
    messageDetailCurrent=message;
    const meta=message.external||{},summary=isSummaryOnly(message),link=messageLink(meta.url,meta.kind==='task_center'?'打开学习通原任务':'打开学习通原消息');
    detail.innerHTML=`${messageReadStatus(message)}${message.sample||isCompanionDemo(message)?pill('示例','outline'):''}<dl class="message-detail-meta"><div><dt>消息来源</dt><dd>${esc(messageSourceLabel(message))}</dd></div><div><dt>${message.supplement?'通知时间依据':'发布时间'}</dt><dd>${esc(messageTimeLabel(message))}</dd></div><div><dt>截止时间</dt><dd>${esc(messageDeadlineLabel(message))}</dd></div><div><dt>课程 / 班级</dt><dd>${esc(message.course||'未填写课程')} · ${esc(message.scope||'未设置班级')}</dd></div>${message.chat_import?`<div><dt>发件人</dt><dd>${esc(message.chat_import.sender||'未填写')}</dd></div>`:''}</dl><div class="message-detail-actions">${link}<button id="messageCopy" class="text-button">复制原文</button><button id="messageRefresh" class="text-button">刷新详情</button></div><section class="message-section"><h3>${summary?'已收到的通知摘要':'已收到的原文'}</h3><pre id="messageDetailText" class="message-detail-text">${esc(message.text)}</pre></section>${messageAttachmentsHTML(meta.attachments,'messageAttachments',meta.kind==='task_center'?message.id:'')}${messageRelatedHTML(message.related)}`;
    if(message.supplement){
      detail.insertAdjacentHTML('beforeend',`<p class="helper">此内容由用户补充${message.supplement.filename?' · 文件：'+esc(message.supplement.filename):''}。原通知单独保留。</p><button class="button" data-message-detail="${esc(message.supplement.original_message_id)}">查看原消息</button>`);
    }else{
      detail.insertAdjacentHTML('beforeend','<div id="messageSupplements"></div>');
    }
    const fields=[['补充时间',dateLabel(message.supplement?.added_at)],['接收时间',dateLabel(message.received_at)],['会话',meta.conversation],['发件人',meta.sender||(meta.direction==='sent'?'本人':'')],['网页时间标记',meta.display_time],['消息编号',meta.message_id]];
    detail.insertAdjacentHTML('beforeend',`<details class="evidence message-technical"><summary>更多来源信息</summary><dl class="message-detail-meta">${fields.filter(([,value])=>value).map(([name,value])=>`<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>${message.trace?.length?traceHTML(message.trace):''}</details>`);
    if(!message.supplement){
      try{
        const result=await json('/api/messages/'+id+'/supplements');
        if(!current())return;
        $('#messageSupplements').innerHTML=result.records.length?`<details class="evidence"><summary>人工补充记录（${result.records.length}）</summary>${result.records.map(record=>`<article class="supplement-record"><div><strong>${esc({pending:'待确认',confirmed:'已确认',dismissed:'已忽略草稿',unrecognized:'尚未识别任务'}[record.status])}</strong><span class="helper">${esc(dateLabel(record.created_at))}${record.filename?' · '+esc(record.filename):''}</span></div>${record.file_partial?'<p class="helper">文件仅读取部分文字，仍需核对。</p>':''}<pre class="message-detail-text">${esc(record.text)}</pre></article>`).join('')}</details>`:'';
      }catch(error){if(current())$('#messageSupplements').textContent='补充记录暂时无法读取：'+error.message}
    }
  }catch(error){
    if(current())detail.innerHTML=`<p class="error-text" role="alert">${esc(error.message)}</p><button id="messageRefresh" class="button">重新读取详情</button>`;
  }
}
$('#messageDialog').addEventListener('close',()=>{if(!$('#messageDialog').open){messageDetailGeneration++;messageDetailCurrent=null}});
function setSupplementTargets(targets,target=''){
  const choices=targets.length?targets:[{key:'auto',title:'按补充正文自动识别',course:''}];
  $('#supplementTarget').innerHTML=(choices.length>1?'<option value="" disabled>请选择对应任务</option>':'')+choices.map(item=>`<option value="${esc(item.key)}">${esc([item.course,item.title].filter(Boolean).join(' · '))}</option>`).join('');
  $('#supplementTarget').value=choices.some(item=>item.key===target)?target:choices.length===1?choices[0].key:'';
  $('#supplementTarget').disabled=choices.length===1;
}
async function openSupplement(id,target=''){
  const generation=++supplementGeneration;
  const context=await json('/api/messages/'+id+'/supplements');
  if(generation!==supplementGeneration)return;
  supplementSourceId=id;
  $('#supplementText').value='';$('#supplementError').textContent='';$('#supplementSubmit').disabled=false;
  setSupplementTargets(context.targets,target);
  $('#supplementReference').value=context.reference_known?cnLocalTime(new Date(context.reference_at)):'';
  $('#supplementTimeOptions').open=!context.reference_known;
  for(const dialog of [$('#messageDialog'),$('#taskDialog')])if(dialog.open)dialog.close();
  $('#supplementDialog').showModal();$('#supplementText').focus();
}
$('#supplementDialog').addEventListener('close',()=>{supplementGeneration++});
$('#supplementForm').addEventListener('submit',async event=>{
  event.preventDefault();$('#supplementError').textContent='';
  const generation=supplementGeneration,sourceId=supplementSourceId,button=$('#supplementSubmit');button.disabled=true;
  try{
      const reference=$('#supplementReference').value;
      const body={text:$('#supplementText').value,target:$('#supplementTarget').value};
      if(reference)body.reference_at=reference+(reference.length===16?':00':'')+'+08:00';
      const result=await json('/api/messages/'+sourceId+'/supplements',{method:'POST',body});
      if(generation!==supplementGeneration||sourceId!==supplementSourceId)return;
      if($('#supplementText').value!==body.text||$('#supplementTarget').value!==body.target||$('#supplementReference').value!==reference){
        const context=await json('/api/messages/'+sourceId+'/supplements');
        if(generation!==supplementGeneration||sourceId!==supplementSourceId)return;
        setSupplementTargets(context.targets,$('#supplementTarget').value);
        $('#supplementError').textContent='上一份补充已保存，当前修改尚未提交，请再次生成草稿。';return;
      }
      if(!result.proposals.length){$('#supplementError').textContent='补充已保存，但未生成待确认草稿。请补充任务名称和具体要求后重试，或在原消息查看补充记录。';return}
      $('#supplementDialog').close();inboxTab=result.proposals.some(proposal=>proposal.action==='conflict')?'conflicts':'pending';view='inbox';await refresh();showView('inbox');toast('补充草稿已生成，确认后更新原任务');
  }catch(error){if(generation===supplementGeneration&&sourceId===supplementSourceId)$('#supplementError').textContent=error.message}
  finally{if(generation===supplementGeneration&&sourceId===supplementSourceId)button.disabled=false}
});
let noticePlatformPrevious='manual';
function updateImportPlatform(){
  const platform=$('#noticePlatform').value,chat=platform!=='manual';
  $('#noticeSourceField').hidden=chat;$('#noticeSource').required=!chat;
  $('#noticeSenderField').hidden=!chat;$('#noticeScope').required=chat;
  $('#noticeScopeLabel').textContent=chat?'群名 / 会话':'班级 / 分组（可选）';
  $('#noticeScope').placeholder=chat?'填写原群名或会话名':'例如：计科 1 班';
  $('#noticeTime').required=!chat;
  $('#noticeTimeHelp').textContent=chat?'填写原消息时间（北京时间）；不清楚可留空，不按导入时间推算。':'北京时间；“明天”等以此为准。';
  if(chat&&noticePlatformPrevious==='manual')$('#noticeTime').value='';
  if(!chat&&noticePlatformPrevious!=='manual')$('#noticeTime').value=cnLocalTime();
  noticePlatformPrevious=platform;
}
$('#noticePlatform').addEventListener('change',updateImportPlatform);
function openImport(){
  if($('#messageDialog').open)$('#messageDialog').close();
  updateImportPlatform();$('#noticeTime').value=$('#noticePlatform').value==='manual'?cnLocalTime():'';$('#noticeMode').value=state.agent.mode==='agent'?'agent':'rules';$('#importError').textContent='';
  $('#importDialog').showModal();
}
function traceHTML(trace){return `<details class="trace-panel"><summary>工具执行轨迹 · ${trace.length} 次调用</summary>${trace.map((t,i)=>`<p>${i+1}. ${esc(t.tool)}</p><pre>${esc(JSON.stringify(t.result,null,2).slice(0,6000))}</pre>`).join('')}</details>`}
async function download(which){
  const response=await api(which==='calendar'?'/api/calendar.ics':which==='acceptance'?'/api/chaoxing/desktop/acceptance':'/api/export.json');
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=which==='calendar'?'courseinbox.ics':which==='acceptance'?'courseinbox-desktop-check.json':'courseinbox-backup.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);
}
async function notify(summary){
  if(!('Notification' in window)||Notification.permission!=='granted'||localStorage.getItem('courseinbox-reminders')!=='enabled')return;
  for(const r of summary.reminders){
    const key='courseinbox-notified:'+r.task_id+':'+r.deadline+':'+r.level;
    if(localStorage.getItem(key))continue;
    new Notification(r.overdue?'课程任务已逾期':'课程任务即将截止',{body:r.course+' · '+r.title+'\n'+formatDeadline(r.deadline),tag:r.task_id,icon:'/favicon.svg'});
    localStorage.setItem(key,new Date().toISOString());
  }
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.dataset.attachmentDownload){await busy(button,()=>downloadAttachment(button));return}
    if(button.dataset.queryExample){$('#assistantQuestion').value=button.dataset.queryExample;$('#assistantQuestion').focus();return}
    if(button.hasAttribute('data-close')){button.closest('dialog').close();return}
    if(button.dataset.view){selectedMessages.clear();if(button.dataset.inboxTab)inboxTab=button.dataset.inboxTab;showView(button.dataset.view);return}
    if(button.dataset.inboxTab){selectedMessages.clear();inboxTab=button.dataset.inboxTab;renderInbox();return}
    if(button.id==='importOpen'||button.hasAttribute('data-open-import')){openImport();return}
    if(button.id==='refreshButton'){await busy(button,()=>refresh());toast('数据已刷新');return}
    if(button.hasAttribute('data-demo')){await busy(button,async()=>{await json('/api/demo',{method:'POST',body:{}});await refresh();toast('示例数据已加载，全部标注为示例')});return}
    if(button.dataset.detail){if($('#messageDialog').open)$('#messageDialog').close();await openTask(button.dataset.detail);return}
    if(button.dataset.restoreTask){await busy(button,()=>restoreTask(button.dataset.restoreTask,Number(button.dataset.version),null,button.dataset.restoreStatus||'cancelled'));return}
    if(button.dataset.adoptPlatform){
      await json('/api/tasks/'+button.dataset.adoptPlatform+'/adopt-platform-status',{method:'POST',body:{expected_version:Number(button.dataset.version),observation_id:button.dataset.observation}});
      await refresh();await openTask(button.dataset.adoptPlatform);return;
    }
    if(button.dataset.messageDetail){await openMessage(button.dataset.messageDetail);return}
    if(button.id==='messageRefresh'){await openMessage($('#messageDetail').dataset.messageId);return}
    if(button.id==='messageCopy'){
      if(!messageDetailCurrent)return;
      await navigator.clipboard.writeText(messageDetailCurrent.text);toast('原文已复制');return;
    }
    if(button.dataset.messageProposal){
      const id=button.dataset.messageProposal;$('#messageDialog').close();await refresh(false);
      const proposal=state.proposals.find(item=>item.id===id);
      if(!proposal){toast('草稿状态已变化，请重新打开消息详情',true);return}
      inboxTab=proposal.action==='conflict'?'conflicts':'pending';showView('inbox');
      const card=$('[data-proposal="'+id+'"]');card?.scrollIntoView({block:'center'});card?.querySelector('input,button')?.focus();return;
    }
    if(button.dataset.supplement){await openSupplement(button.dataset.supplement,button.dataset.supplementTarget||'');return}
    if(button.id==='messagesNext'||button.id==='messagesPrevious'){await busy(button,()=>loadMessagePage(messagePageOffset+(button.id==='messagesNext'?MESSAGE_PAGE_SIZE:-MESSAGE_PAGE_SIZE)));$('#messageList')?.scrollIntoView({block:'start'});return}
    if(button.id==='clearSelectedMessages'||button.id==='clearAllMessages'){await busy(button,()=>prepareCleanup(button.id==='clearAllMessages'));return}
    if(button.id==='cleanupCancel'){$('#cleanupDialog').close();cleanupIds=[];return}
    if(button.id==='cleanupConfirmButton'){
      const snapshot=[...cleanupIds];
      await busy(button,async()=>{const result=await json('/api/messages/clear',{method:'POST',body:{ids:snapshot}});$('#cleanupDialog').close();cleanupIds=[];selectedMessages.clear();messagePageOffset=0;await refresh();toast(`已清理 ${result.cleared} 条消息，任务和关联原文已保留`)});return;
    }
    if(button.id==='desktopRecheck'){await busy(button,async()=>{await json('/api/chaoxing/desktop/recheck',{method:'POST',body:{}});await loadDesktopStatus();toast('已请求重新检查，沿用当前登录状态')});return}
    if(button.id==='taskInventoryRepair'||button.hasAttribute('data-inventory-repair')||button.hasAttribute('data-inventory-section')){
      if(taskInventoryRepairRunning)return;taskInventoryRepairRunning=true;paintInventoryRepair(taskInventorySnapshot);button.disabled=true;button.setAttribute('aria-busy','true');
      try{
        const body=button.dataset.inventorySection?{sections:[button.dataset.inventorySection]}:button.dataset.inventoryRepair?{keys:[button.dataset.inventoryRepair]}:{};
        const rows=body.sections?taskInventorySnapshot?.sections:taskInventorySnapshot?.items;
        const keys=body.sections||body.keys||(rows||[]).filter(item=>['missing','unrecognized'].includes(item.state)||item.detail_state==='pending').map(item=>item.key);
        const before=new Map((rows||[]).filter(item=>keys.includes(item.key)).map(item=>[item.key,item.checked_at]));
        const result=await json('/api/chaoxing/desktop/repair',{method:'POST',body});
        taskInventoryRepairNotice={count:result.sections_requested||result.requested||0,sections:!!body.sections,keys,before,reextracted:result.reextracted||0};
        paintInventoryRepair(taskInventorySnapshot);toast(taskInventoryRepairNotice.count?'补收已安排，进度会在页面中更新':'当前没有可自动补收的缺失项');
      }catch(error){if($('#taskInventoryRepairStatus')){$('#taskInventoryRepairStatus').hidden=false;$('#taskInventoryRepairStatus').textContent='补收请求失败：'+error.message}taskInventoryRepairNotice=null;throw error}
      finally{taskInventoryRepairRunning=false;button.disabled=false;button.removeAttribute('aria-busy');taskInventorySignature='';await loadDesktopStatus()}return;
    }
    if(button.id==='taskInventoryScope'){if(desktopStatusLoading)return;taskInventoryAttentionOnly=!taskInventoryAttentionOnly;taskInventoryOffset=0;taskInventorySignature='';await loadDesktopStatus();return}
    if(['taskInventoryPrevious','taskInventoryNext','taskInventoryRefresh'].includes(button.id)){
      if(desktopStatusLoading)return;
      if(button.id!=='taskInventoryRefresh')taskInventoryOffset=Math.max(0,taskInventoryOffset+(button.id==='taskInventoryNext'?20:-20));
      await loadDesktopStatus();return;
    }
    if(button.dataset.linkProposal){await busy(button,async()=>{await json('/api/proposals/'+button.dataset.linkProposal+'/confirm',{method:'POST',body:{link_only_to:button.dataset.linkTask,expected_version:Number(button.dataset.linkVersion)}});await refresh();toast('原文已关联，已有任务的截止和进度保持不变')});return}
    if(button.dataset.confirm){
      const card=button.closest('.proposal-card');$('.proposal-error',card).textContent='';
      const fields=proposalEdits(card,true),p=state.proposals.find(p=>p.id===button.dataset.confirm);
      const action=proposalAction(p,fields,card.dataset.dirty==='true');
      if(p.candidate.operation==='update'&&!p.target_id){
        const target=matchingUpdateTask(fields);
        if(!target)throw new Error('请先匹配到原任务；截止变更不能新建作业。');
        fields.expected_version=target.version;
      }
      if(button.dataset.conflictResolution)fields.resolution=button.dataset.conflictResolution;
      await busy(button,async()=>{try{await json('/api/proposals/'+button.dataset.confirm+'/confirm',{method:'POST',body:fields});await refresh();toast(button.dataset.conflictResolution==='current'?'已保留当前任务并关联来源':button.dataset.conflictResolution==='incoming'?'已采用新消息':action==='update'?'变更已确认':action==='merge'?'来源已合并':'任务已确认')}catch(error){$('.proposal-error',card).textContent=error.message;throw error}});return;
    }
    if(button.dataset.reanalyzeMessage){await busy(button,async()=>{await json('/api/messages/'+button.dataset.reanalyzeMessage+'/reanalyze',{method:'POST',body:{mode:'rules'}});inboxTab='pending';view='inbox';await refresh();toast('草稿已刷新，请重新核对')});return}
    if(button.dataset.dismiss){await busy(button,async()=>{await json('/api/proposals/'+button.dataset.dismiss+'/dismiss',{method:'POST',body:{}});await refresh();toast('草稿已忽略，消息原文仍保留')});return}
    if(button.hasAttribute('data-month')){month=button.dataset.month==='0'?new Date(cnLocalTime().slice(0,10)+'T12:00:00'):new Date(month.getFullYear(),month.getMonth()+Number(button.dataset.month),1);renderCalendar();return}
    if(button.dataset.download){await busy(button,()=>download(button.dataset.download));return}
    if(button.id==='tokenReveal'){const input=$('#pairToken');input.value=token;input.type=input.type==='password'?'text':'password';button.textContent=input.type==='text'?'隐藏':'显示';return}
    if(['wechatPushSave','wechatPushTest','wechatPushClear'].includes(button.id)){await changeWechatPush(button);return}
    if(['mobileRemindersToggle','mobileRemindersPair'].includes(button.id)||button.hasAttribute('data-reminder-revoke')){await changeMobileReminders(button);return}
    if(button.hasAttribute('data-reminder-copy-address')){await navigator.clipboard.writeText(button.dataset.reminderCopyAddress);toast('手机网页地址已复制');return}
    if(button.hasAttribute('data-mobile-messages')){inboxTab='messages';showView('inbox');return}
    if(button.dataset.copyField){const value=$('#'+button.dataset.copyField).value;if(!value)throw new Error('配对信息暂不可用。');await navigator.clipboard.writeText(value);toast('已复制');return}
    if(button.id==='tokenCopy'){await navigator.clipboard.writeText(token);toast('配对令牌已复制');return}
    if(button.id==='webTokenReveal'||button.id==='webTokenCopy'){
      const pairing=await json('/api/chaoxing/pairing'),input=$('#webPairToken');
      if(button.id==='webTokenCopy'){await navigator.clipboard.writeText(pairing.token);toast('网页同步专用令牌已复制')}
      else{input.value=pairing.token;input.type=input.type==='password'?'text':'password';button.textContent=input.type==='text'?'隐藏':'显示'}
      return;
    }
    if(button.id==='desktopLogout'){
      if(!window.confirm('退出后将清除这台电脑保存的学习通登录状态；已接收的消息和任务会保留。确定退出吗？'))return;
      await busy(button,async()=>{await json('/api/chaoxing/desktop/logout',{method:'POST',body:{}});await loadDesktopStatus();toast('已退出学习通账号，本地消息和任务已保留')});return;
    }
    if(['desktopLogin','desktopResume','desktopPause','desktopLoginWindow'].includes(button.id)){
      event.preventDefault();await busy(button,async()=>{const action=button.id==='desktopPause'?'pause':button.id==='desktopResume'?'resume':'login';await json('/api/chaoxing/desktop/'+action,{method:'POST',body:button.id==='desktopLoginWindow'?{visible:true}:{}});await loadDesktopStatus()});return;
    }
    if(button.id==='savePackages'){await busy(button,async()=>{await json('/api/settings',{method:'POST',body:{allowed_packages:$('#packageList').value.split('\n').map(x=>x.trim()).filter(Boolean)}});toast('应用白名单已保存')});return}
    if(button.id==='assistantOpen'){$('#assistantMode').textContent=state.agent.mode==='agent'?'模型通过工具查询；不会直接修改任务。':'本地规则查询；自由问答需配置模型。';$('#assistantDialog').showModal();return}
    if(button.hasAttribute('data-notifications')){if(!('Notification' in window))throw new Error('此浏览器暂不支持系统通知。');const permission=await Notification.requestPermission();if(permission==='granted'){localStorage.setItem('courseinbox-reminders','enabled');await notify(state.summary);toast('已开启页面运行期间的截止提醒')}else{toast('系统通知未授权，页面内仍显示截止提醒',true)}return}
  }catch(error){toast(error.message,true)}
});
document.addEventListener('input',event=>{const card=event.target.closest('.proposal-card');if(card&&event.target.dataset.field){card.dataset.dirty='true';syncProposalAction(card)}});
document.addEventListener('change',async event=>{
  const input=event.target;
  try{
    if(input.hasAttribute('data-message-select')){if(input.checked)selectedMessages.add(input.dataset.messageSelect);else selectedMessages.delete(input.dataset.messageSelect);syncMessageSelection();return}
    if(input.id==='selectPageMessages'){selectedMessages.clear();for(const checkbox of content.querySelectorAll('[data-message-select]')){checkbox.checked=input.checked;if(input.checked)selectedMessages.add(checkbox.dataset.messageSelect)}syncMessageSelection();return}
    if(input.hasAttribute('data-precision')){const card=input.closest('.proposal-card');card.dataset.dirty='true';const field=$('[data-field="deadline"]',card);field.disabled=input.value==='unknown';field.type=input.value==='minute'?'datetime-local':'date';field.value='';syncProposalAction(card);return}
    if(input.closest('.proposal-card')&&input.dataset.field){const card=input.closest('.proposal-card');card.dataset.dirty='true';syncProposalAction(card);return}
    if(input.dataset.status){
      const task=state.tasks.find(t=>t.id===input.dataset.status),status=input.value;
      input.value=task.status==='in_progress'?'pending':task.status;
      if(!await confirmTaskStatus(task,status))return;
      const updated=await json('/api/tasks/'+task.id,{method:'PATCH',body:{status,expected_version:task.version}});await refresh();taskStatusSaved(updated,task.status);return;
    }
    if(input.dataset.detailStatus){
      const id=input.dataset.detailStatus,version=Number($('#taskDetail').dataset.version),previous=$('#taskDetail').dataset.status,status=input.value;
      input.value=previous==='in_progress'?'pending':previous;
      if(!await confirmTaskStatus({title:$('#detailTitle').textContent,status:previous},status))return;
      if(detailId!==id||Number($('#taskDetail').dataset.version)!==version)throw new Error('任务已更新，请重新核对。');
      await saveDetail({status});return;
    }
    if(input.hasAttribute('data-check')){const values=Array.from($('#taskDetail').querySelectorAll('[data-check]')).map(i=>i.checked);await saveDetail({checklist:values});return}
  }catch(error){toast(error.message,true);if(detailId&&$('#taskDialog').open)await openTask(detailId);else await refresh()}
});
$('#noticeFile').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;
  const status=$('#fileStatus');status.textContent='正在本地识别文件…';$('#importSubmit').disabled=true;
  try{
    if(file.size>8*1024*1024)throw new Error('文件超过 8 MB，请缩小后再导入。');
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file)});
    const result=await json('/api/files/extract',{method:'POST',body:{filename:file.name,content_base64:data}});
    $('#noticeText').value=result.text;status.textContent=(result.engine.startsWith('windows-pdf')?'Windows PDF 本地识别':result.engine.startsWith('windows-ocr')?'Windows 中文 OCR':result.engine)+(result.partial?' · 仅读取部分页面，请核对原文件并分段补充。':' · 已提取，请检查识别文字后生成草稿。');
  }catch(error){status.textContent=error.message;toast(error.message,true)}finally{$('#importSubmit').disabled=false}
});
$('#importForm').addEventListener('submit',async event=>{
  event.preventDefault();$('#importError').textContent='';
  await busy($('#importSubmit'),async()=>{
    try{
      const platform=$('#noticePlatform').value,time=$('#noticeTime').value;
      const body={text:$('#noticeText').value,course:$('#noticeCourse').value,mode:$('#noticeMode').value};
      if(platform==='manual')Object.assign(body,{source:$('#noticeSource').value,scope:$('#noticeScope').value,captured_at:time+':00+08:00'});
      else Object.assign(body,{platform,conversation:$('#noticeScope').value,sender:$('#noticeSender').value,published_at:time?time+':00+08:00':null});
      const result=await json(platform==='manual'?'/api/messages':'/api/connectors/chat/import',{method:'POST',body});
      $('#importDialog').close();inboxTab='pending';view='inbox';await refresh();showView('inbox');
      $('#noticeText').value='';$('#noticeFile').value='';$('#fileStatus').textContent='';
      toast(result.duplicate?'重复消息已关联，未重复创建':result.proposals.length?`已生成 ${result.proposals.length} 条待确认草稿`:'消息已保存，没有识别到学习任务');
    }catch(error){$('#importError').textContent=error.message}
  });
});
$('#assistantForm').addEventListener('submit',async event=>{
  event.preventDefault();await busy($('#assistantSubmit'),async()=>{
    $('#assistantAnswer').hidden=false;$('#assistantAnswer').textContent='正在查询任务…';$('#assistantTrace').innerHTML='';
    try{const scope=$('#assistantScope').value.trim();const result=await json('/api/assistant',{method:'POST',body:{question:$('#assistantQuestion').value,course:$('#assistantCourse').value.trim(),scope:scope||null}});$('#assistantAnswer').textContent=result.answer;$('#assistantTrace').innerHTML=result.trace?.length?traceHTML(result.trace):''}catch(error){$('#assistantAnswer').textContent=error.message}
  });
});
$('#authForm').addEventListener('submit',async event=>{
  event.preventDefault();token=$('#authToken').value.trim();try{await refresh();sessionStorage.setItem('courseinbox-token',token);$('#authDialog').close()}catch(error){$('#authError').textContent=error.message}
});
$('#authDialog').addEventListener('cancel',e=>e.preventDefault());
async function boot(){
  content.innerHTML='<div class="loading">正在打开你的学习空间…</div>';
  try{const response=await fetch('/api/bootstrap');if(response.ok)token=(await response.json()).token;else token=sessionStorage.getItem('courseinbox-token')||'';await refresh(false);view=location.hash.slice(1)||'today';if(!['today','tasks','inbox','calendar','mobile','sync','evaluation'].includes(view))view='today';renderView();openDesktopLink().catch(error=>toast(error.message,true))}catch(error){content.innerHTML=empty('连接尚未完成','输入电脑端的访问令牌后可打开学习空间。');$('#authDialog').showModal()}
}
async function openDesktopLink(){
  const query=new URLSearchParams(location.search),message=query.get('message'),task=query.get('task');
  if(message&&/^[a-f0-9]{32}$/.test(message))await openMessage(message);
  else if(task&&/^[a-f0-9]{32}$/.test(task))await openTask(task);
}
let polling=false;
setInterval(async()=>{
  if(!token||polling)return;
  polling=true;
  try{
    const summary=await json('/api/dashboard');await notify(summary);
    if(document.querySelector('dialog[open]'))return;
    if(view==='inbox'||view==='mobile'){
      if(view==='inbox'&&selectedMessages.size){$('.sync-label').textContent='选中的消息已保留，可完成清理后刷新';return}
      const next=await json('/api/state');
      const messagesChanged=next.message_total!==state.message_total||next.messages.length!==state.messages.length||next.messages.some((message,i)=>message.id!==state.messages[i]?.id);
      const proposalsChanged=next.proposals.length!==state.proposals.length||next.proposals.some((proposal,i)=>proposal.id!==state.proposals[i]?.id||proposal.source_count!==state.proposals[i]?.source_count);
      const archivedChanged=(next.archived_proposals||[]).length!==(state.archived_proposals||[]).length;
      if(!messagesChanged&&!proposalsChanged&&!archivedChanged)return;
      const dirty=content.querySelector('.proposal-card[data-dirty="true"]');
      if(view==='mobile'){
        await refresh(false,next);
        $('.sync-label').textContent='有新消息，请打开收件箱';
      }else if(document.activeElement?.matches('input,textarea,select')||dirty){
        $('#inboxBadge').textContent=next.proposals.length;
        $('.sync-label').textContent=dirty?'有新消息，当前编辑未保存':'有新消息，完成输入后自动显示';
      }else await refresh(true,next);
    }else if(!document.activeElement?.matches('input,textarea,select'))await refresh();
  }catch{$('.sync-label').textContent='连接已断开'}finally{polling=false}
},15000);
boot();
