'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const reader=fs.readFileSync(path.join(root,'android/app/src/main/assets/mobile-reader.js'),'utf8');
const parser=fs.readFileSync(path.join(root,'browser-companion/parser.js'),'utf8');
const notices=fs.readFileSync(path.join(root,'browser-companion/notices.js'),'utf8');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();let body='';const responses=new Map();
  await page.route('https://**/*',route=>route.fulfill(responses.get(route.request().url())||{status:200,contentType:'text/html; charset=utf-8',body}));
  async function poll(url,html){body=html;await page.goto(url);await page.evaluate(parser);await page.evaluate(notices);await page.evaluate(reader);return page.evaluate(()=>CourseInboxMobileReader.poll());}
  let result=await poll('https://passport2.chaoxing.com/login','<img id="quickCode" src="data:image/png;base64,aA==">');
  assert.equal(result.state,'waiting_scan');assert.equal(result.messages.length,0);assert.equal(result.authenticated,false,'showing a login page is not authenticated');
  const portalMenu='<div class="menu-list"><ul class="menu-list-ul"><li>课程</li><li>消息</li></ul></div>';
  const portalShell='<div class="header"><ul class="nav fr"><li class="user">示例账号</li></ul></div><div class="con"><div class="con-left con-left-float showIcon"><div class="user-block"><img class="head-img"><p class="user-name">示例同学</p></div>'+portalMenu+'</div><div class="con-right"><div class="right-con" id="mainright">我学的课</div></div></div>';
  result=await poll('https://i.chaoxing.com/base?courseId=fixture',portalShell);
  assert.equal(result.state,'authenticated','the signed-in course homepage does not need a notice iframe');assert.equal(result.authenticated,true);assert.deepEqual(result.messages,[],'portal login evidence must not become collected messages');
  result=await poll('https://i.chaoxing.com/',portalShell);
  assert.equal(result.authenticated,true,'the portal root can render the same signed-in navigation');
  result=await poll('https://i.chaoxing.com/base',portalShell.replace('class="menu-list"','class="menu-list" style="display:none"'));
  assert.equal(result.state,'authenticated','collapsing only the menu preserves the visible account evidence');assert.equal(result.authenticated,true);assert.deepEqual(result.messages,[]);
  for(const [url,html,reason] of [
   ['https://i.chaoxing.com/base','<main>课程 消息 收件箱</main>','body text is not signed-in navigation'],
   ['https://i.chaoxing.com/base',portalMenu,'menu labels alone do not establish the portal shell'],
   ['https://i.chaoxing.com/base',portalShell.replace('<div class="header">','<div class="header" hidden>'),'hidden account header does not establish a rendered session'],
   ['https://i.chaoxing.com/base',portalShell.replace('class="con-left con-left-float showIcon"','class="con-left con-left-float showIcon" hidden'),'a fully hidden sidebar cannot prove the rendered account'],
   ['https://i.chaoxing.com/base',portalShell.replace('class="user-name"','class="unknown"'),'the sidebar account block is required'],
   ['https://i.chaoxing.com/base',portalShell.replace('<li>课程</li>','<li>其他</li>'),'the course menu is required'],
   ['https://i.chaoxing.com/base',portalShell.replace('<li>消息</li>','<li>其他</li>'),'the message menu is required'],
   ['https://i.chaoxing.com/base','<div hidden>'+portalShell+'</div>','hidden menu remnants do not establish a rendered session'],
   ['https://i.chaoxing.com/unrecognized',portalShell,'unknown portal paths stay unrecognized'],
   ['https://www.chaoxing.com/base',portalShell,'another official host is not the personal portal'],
   ['https://i.chaoxing.com/base',portalShell+'<form><input type="password"></form>','a login form overrides portal remnants'],
   ['https://i.chaoxing.com/base',portalShell+'<form><input autocomplete="one-time-code"></form>','verification overrides portal remnants'],
   ['https://i.chaoxing.com/base',portalShell+'<div id="captcha">请完成验证</div>','captcha verification overrides portal remnants'],
   ['https://i.chaoxing.com/base',portalShell+'<iframe src="https://passport2.chaoxing.com/login"></iframe>','an embedded login page overrides portal evidence'],
   ['https://i.chaoxing.com/base','<iframe hidden src="https://notice.chaoxing.com/pc/notice/myNotice"></iframe>','a hidden notice iframe is not rendered session evidence']
  ]){
   result=await poll(url,html);assert.equal(result.state,'unrecognized',reason);assert.equal(result.authenticated,false,reason);assert.deepEqual(result.messages,[]);
  }
  result=await poll('https://i.chaoxing.com/base',portalShell+'<img id="quickCode" src="data:image/png;base64,aA==">');
  assert.equal(result.state,'waiting_scan');assert.equal(result.authenticated,false,'official QR confirmation overrides menu remnants');
  result=await poll('https://passport2.chaoxing.com/login',portalShell);
  assert.equal(result.state,'waiting_scan');assert.equal(result.authenticated,false,'official login URLs never inherit portal evidence');
  result=await poll('https://i.chaoxing.com/base','<iframe src="https://notice.chaoxing.com/pc/notice/myNotice"></iframe>');
  assert.equal(result.authenticated,true,'an existing notice iframe remains valid portal evidence');
  const courseCard='<div class="course clearfix learnCourse"><div class="course-cover"><img width="120" height="80"></div><div class="course-info"><h3><a><span class="course-name">示例课程</span></a></h3></div></div>';
  const courseShell='<div id="divbox" class="box"><div class="content"><div class="main"><div class="course-tab">我学的课</div><div class="course-con"><div class="course-list-con"><div id="courselistArea" class="courselistArea"><div><div id="courseList" class="course-list"><div id="stuNormalCourseListDiv">'+courseCard+'</div></div></div></div></div></div></div></div></div>';
  result=await poll('https://mooc2-ans.chaoxing.com/visit/interaction',courseShell);
  assert.equal(result.state,'authenticated','a rendered official course list proves the standalone course session');assert.equal(result.authenticated,true);assert.deepEqual(result.messages,[],'course cards are login evidence, not supported message sources');
  result=await poll('https://mooc2-ans.chaoxing.com/visit/interaction',courseShell.replace('learnCourse','teachCourse'));
  assert.equal(result.authenticated,true,'rendered teaching courses provide the same session evidence');
  for(const [url,html,reason] of [
   ['https://mooc2-ans.chaoxing.com/visit/interaction',courseShell.replace(courseCard,''),'an empty course skeleton cannot prove login'],
   ['https://mooc2-ans.chaoxing.com/visit/interaction',courseShell.replace('class="course-cover"','class="unknown"'),'course placeholders without a cover are not evidence'],
   ['https://mooc2-ans.chaoxing.com/visit/interaction',courseShell.replace('class="course-name"','class="unknown"'),'course placeholders without a name are not evidence'],
   ['https://mooc2-ans.chaoxing.com/visit/interaction',courseShell.replace('示例课程',''),'an unrendered empty course name is not evidence'],
   ['https://mooc2-ans.chaoxing.com/visit/interaction','<div hidden>'+courseShell+'</div>','hidden course remnants cannot prove a rendered session'],
   ['https://mooc2-ans.chaoxing.com/visit/unknown',courseShell,'course evidence is constrained to the known list route'],
   ['https://mooc.chaoxing.com/visit/interaction',courseShell,'course evidence is constrained to the known list host'],
   ['https://mooc2-ans.chaoxing.com/visit/interaction',courseShell+'<input autocomplete="one-time-code">','course remnants do not override a verification gate']
  ]){
   result=await poll(url,html);assert.equal(result.state,'unrecognized',reason);assert.equal(result.authenticated,false,reason);assert.deepEqual(result.messages,[]);
  }
  result=await poll('https://fe.chaoxing.com/front/webim/index.html','<div class="chat-header"><b class="chat-name">软件工程群</b></div><div class="conversation-list"><div class="conversation-item is-selected"><span class="name">软件工程群</span></div></div><div class="message-area"><div class="time-stamp">2026-10-10 10:00</div><div class="message-row is-other" data-msg-id="m123"><span class="sender-name">老师</span><p class="bubble-text">第三次作业截止10月12日</p></div></div>');
  assert.equal(result.state,'connected');assert.equal(result.messages.length,1);assert.equal(result.messages[0].text,'第三次作业截止10月12日');assert.equal(result.messages[0].conversation,'软件工程群');assert.equal(result.authenticated,true,'rendered chat provides explicit authentication evidence');
  await page.evaluate(()=>{CourseInboxChaoxing.extractDocument=()=>{throw new Error('fixture reader failure')}});
  result=await page.evaluate(()=>CourseInboxMobileReader.poll().catch(()=>({state:'threw'})));
  assert.equal(result.state,'error','reader rejection must not become a partially authenticated session');assert.equal(result.authenticated,false);
  result=await poll('https://fe.chaoxing.com/front/webim/index.html',`<div class="chat-header"><b class="chat-name"></b></div><div class="conversation-item is-selected" id="previous"><span class="name">A群</span></div><div class="conversation-list"><div class="conversation-item" id="next"><span class="name">B群</span></div></div><div class="message-area"><div class="message-row is-other" data-msg-id="old"><p class="bubble-text">A原文</p></div></div><script>next.onclick=function(){previous.classList.remove('is-selected');next.classList.add('is-selected');document.querySelector('.chat-name').textContent='A群';document.querySelector('.message-area').innerHTML='<div class="message-row is-other" data-msg-id="new"><p class="bubble-text">B原文</p></div>';setTimeout(function(){document.querySelector('.chat-name').textContent='B群'},100)}</script>`);
  assert.equal(result.messages.length,1);assert.equal(result.messages[0].text,'B原文');assert.equal(result.messages[0].conversation,'B群');
  result=await poll('https://fe.chaoxing.com/front/webim/index.html','<div class="conversation-list"></div>');
  assert.equal(result.state,'loading');assert.equal(result.messages.length,0);
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice','<div class="dataBody"></div>');
  assert.equal(result.state,'loading');assert.equal(result.messages.length,0);
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice','<div class="dataBody">暂无通知</div>');
  assert.equal(result.state,'connected');assert.equal(result.messages.length,0);
  const workTitle='作业:《测试》作业20261015',workUrl='https://notice.chaoxing.com/pc/notice/$CACG$fixture-new-work/detail';
  const workList='<div class="dataBody"><div class="dataBody_item" data-id="fixture-row"><div class="openNotice" data-sendtag="0" data-url="'+workUrl+'"><a class="notice_title">'+workTitle+'</a><span class="notice_time">10-15(星期四) 19:17</span><span class="receiverName">学习通知</span></div></div></div>';
  const workData={status:true,msg:{uuid:'$CACG$fixture-new-work',idCode:'fixture-row',title:workTitle,isRtf:1,rtf_content:'<p>老师发布了新的作业，请完成并提交。</p><script>globalThis.__noticeScriptRan=true</script>',content:'老师发布了新的作业，请完成并提交。',createrName:'学习通知',insertTime:Date.parse('2026-10-15T19:17:00+08:00')}};
  const dataUrl=workUrl.replace(/\/detail$/,'/getNoticeDetail')+'?sendTag=0';
  responses.set(workUrl,{status:200,contentType:'text/html',body:'<h1 id="title"></h1><div class="noticeContent"></div><script>/* Official template fills content from getNoticeDetail. */</script>'});
  responses.set(dataUrl,{status:200,contentType:'application/json',body:JSON.stringify(workData)});
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice',workList);
  assert.equal(result.messages.length,1,'a real-style script-rendered notice must not disappear when static HTML is empty');
  assert.equal(result.messages[0].title,workTitle);assert.equal(result.messages[0].text,'老师发布了新的作业，请完成并提交。');
  assert.equal(result.messages[0].course,'测试');assert.equal(result.messages[0].url,workUrl);
  assert.equal(result.inspected_count,1,'native refresh progress must count the detail request rather than portal authentication');
  assert.equal(Date.parse(result.messages[0].captured_at),Date.parse('2026-10-15T19:17:00+08:00'),'use the source timestamp rather than the scan time');
  assert.equal(await page.evaluate(()=>Boolean(globalThis.__noticeScriptRan)),false,'notice markup must be parsed inertly');
  responses.set(workUrl,{status:200,contentType:'text/html',body:'<h1 id="title">'+workTitle+'</h1><span class="createTime">2026-10-15 19:17</span><span class="createName">学习通知</span><div class="noticeContent"></div>'});
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice',workList);
  assert.equal(result.messages[0]?.text,'老师发布了新的作业，请完成并提交。','rendered header metadata cannot prove that an empty static body has finished loading');
  responses.set(dataUrl,{status:200,contentType:'application/json',body:JSON.stringify({...workData,msg:{...workData.msg,uuid:'$CACG$another-notice'}})});
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice',workList);
  assert.equal(result.messages.length,0,'a response for another notice must never be attributed to this task');assert.equal(result.state,'partial');
  responses.set(dataUrl,{status:200,contentType:'application/json',body:JSON.stringify({status:false,msg:'无权查看'})});
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice',workList);
  assert.equal(result.messages.length,0,'permission rejection cannot become a task');assert.equal(result.state,'partial');
  responses.set(dataUrl,{status:200,contentType:'application/json',body:JSON.stringify({...workData,msg:{...workData.msg,rtf_content:'<img src="https://p.ananas.chaoxing.com/only-image.png">',content:''}})});
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice',workList);
  assert.equal(result.messages.length,0,'image-only content is not a fully read empty notice');assert.equal(result.state,'partial');
  responses.set(dataUrl,{status:200,contentType:'application/json',body:JSON.stringify({...workData,msg:{...workData.msg,rtf_content:'',content:''}})});
  result=await poll('https://notice.chaoxing.com/pc/notice/myNotice',workList);
  assert.equal(result.messages.length,1,'an authoritative empty body still preserves its real title');
  assert.equal(result.messages[0].empty_body_ready,true,'only a confirmed empty response permits title-only native storage');
  responses.clear();
  const requested=[];await page.route('https://notice.chaoxing.com/pc/notice/*/detail',async route=>{requested.push(route.request().url());await route.fulfill(responses.get(route.request().url()));});
  let many='<div class="dataBody">';
  for(let i=0;i<13;i++){
   const url='https://notice.chaoxing.com/pc/notice/$CACG$batch-'+i+'/detail';
   many+='<div class="dataBody_item" data-id="row-'+i+'"><div class="openNotice" data-sendtag="0" data-url="'+url+'"><a class="notice_title">作业:《测试》任务'+i+'</a></div></div>';
   responses.set(url,{status:200,contentType:'text/html',body:'<h1 id="title"></h1><div class="noticeContent"></div>'});
   responses.set(url.replace(/\/detail$/,'/getNoticeDetail')+'?sendTag=0',{status:200,contentType:'application/json',body:JSON.stringify(i===0?{status:false,msg:'不可读取'}:{status:true,msg:{uuid:'$CACG$batch-'+i,idCode:'row-'+i,title:'作业:《测试》任务'+i,isRtf:1,rtf_content:'<p>请提交报告。</p>',createrName:'老师'}})});
  }
  many+='</div>';
  const first=await poll('https://notice.chaoxing.com/pc/notice/myNotice',many);
  const second=await page.evaluate(()=>CourseInboxMobileReader.poll({notice_limit:5}));
  const third=await page.evaluate(()=>CourseInboxMobileReader.poll({notice_limit:3}));
  assert.equal(third.inspected_count,3,'the final batch must not wrap back over already inspected notices');
  assert.equal(first.failed_count+second.failed_count+third.failed_count,1,'one failed notice is reported once per pass');
  assert.equal(requested.length,13);assert.equal(new Set(requested).size,13,'a bounded pass requests each of the thirteen details once');
  await page.unroute('https://notice.chaoxing.com/pc/notice/*/detail');
  responses.clear();
  result=await poll('https://notice.chaoxing.com/pc/notice/n1/detail','<h1 id="title">《英语》课前阅读</h1><div class="noticeContent"><p>请阅读第3章</p></div><span class="createTime">2026-10-10 10:00</span><span class="createName">老师</span>');
  assert.equal(result.messages.length,1);assert.equal(result.messages[0].kind,'course_notice');assert.equal(result.messages[0].message_id,'notice_n1');
  result=await poll('https://chaoxing.com.evil.example/page','<div class="chat-header"><b class="chat-name">群</b></div>');
  assert.equal(result.state,'unsupported');assert.equal(result.messages.length,0);
  console.log('PASS: mobile portal login evidence, login/verification guards, QR detection, chat evidence, unknown-page loading, notice detail and source restriction');
 } finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
