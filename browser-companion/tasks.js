(root=>{
  'use strict';
  const official=(value,base)=>{try{const u=new URL(value,base||(typeof location!=='undefined'?location.href:undefined));if(u.protocol!=='https:'||u.username||u.password||u.port||!['mooc1.chaoxing.com','mooc2-ans.chaoxing.com'].includes(u.hostname))return '';u.hash='';u.searchParams.sort();return u.href}catch{return ''}};
  const fingerprint=value=>{let hash=2166136261;for(let i=0;i<value.length;i++){hash^=value.charCodeAt(i);hash=Math.imul(hash,16777619)}return (hash>>>0).toString(36).padStart(7,'0')};
  const stableTime=value=>String(value||'').replace(/(^|[；;，,\n])[ \t]*(?:剩余|还剩)\s*[:：]?\s*(?:\d+(?:\.\d+)?\s*(?:天|小时|分钟|时|分|秒)\s*)+(?=$|[；;，,\n])/g,'$1').trim();
  const text=(node,selectors)=>{for(const selector of selectors){const value=node.querySelector(selector)?.textContent?.trim();if(value)return value}return ''};
  const publicationSelectors=['.publish-time','.publishTime','.release-time','[data-published-at]'];
  function publication(value){
    const match=String(value||'').match(/(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?(?:[T\s]+(\d{1,2})[:：](\d{2})(?::(\d{2}))?)?/);
    if(!match)return null;
    const [,y,m,d,h,minute,second='00']=match,check=new Date(Date.UTC(+y,+m-1,+d));
    if(check.getUTCFullYear()!==+y||check.getUTCMonth()!==+m-1||check.getUTCDate()!==+d||(+h>23)||(+minute>59)||(+second>59))return null;
    const zoned=String(value).match(/20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})/);
    if(zoned){const date=new Date(zoned[0]);return Number.isNaN(date.getTime())?null:date.toISOString()}
    const date=`${y}-${m.padStart(2,'0')}-${d.padStart(2,'0')}`;
    return h===undefined?date:`${date}T${h.padStart(2,'0')}:${minute}:${second}+08:00`;
  }
  function publicationText(node){
    for(const selector of publicationSelectors)for(const field of node.querySelectorAll(selector)){
      if(field.closest('[hidden],[aria-hidden="true"]')||(field.ownerDocument.defaultView&&!field.getClientRects().length))continue;
      const value=field.getAttribute('data-published-at')||field.textContent?.trim();if(value)return value;
    }
    return '';
  }
  function deadline(value){
    const matches=[...String(value||'').matchAll(/(?:截止|结束|至)[^\d]{0,8}(20\d{2})[-年/.]\s*(\d{1,2})[-月/.]\s*(\d{1,2})日?(?:\s*(\d{1,2})[:：](\d{2}))?/g)];
    const found=matches.at(-1);if(!found)return null;
    const [,year,month,day,hour='00',minute='00']=found;
    const date=`${year}-${month.padStart(2,'0')}-${day.padStart(2,'0')}`;
    return found[4]===undefined?date:`${date}T${hour.padStart(2,'0')}:${minute}:00+08:00`;
  }
  function extractDocument(doc,base,options={}){
    const rootNode=doc.querySelector('[data-course]')||doc.body;
    const course=options.course||rootNode?.dataset?.course||text(doc,['.course-name','.courseName']);
    const className=options.scope||rootNode?.dataset?.class||text(doc,['.class-name','.clazz-name']);
    const rows=[...doc.querySelectorAll('[data-task-id],.work-list-item,.exam-list-item,.workList li,.exam-list li,.task-list li,.bottomList li[data]')];
    return rows.slice(0,100).map((row,index)=>{
      const anchor=row.querySelector('a.task-title,a[title],a[href]'),url=official(row.getAttribute('data')||'',base)||official(anchor?.href||'',base);
      const title=text(row,['.task-title','.work-name','.exam-name','.overHidden2','.title','h3','h4'])||anchor?.textContent?.trim()||'';
      if(!title||!url)return null;
      const identity=(row.dataset.taskId||new URL(url).searchParams.get('workId')||new URL(url).searchParams.get('examId')||new URL(url).searchParams.get('id')||String(index)).replace(/[^A-Za-z0-9_-]/g,'_');
      const deadlineText=text(row,['.deadline','.end-time','.time','.task-time']);
      const publishedText=publicationText(row),publishedAt=publication(publishedText);
      const description=text(row,['.task-description','.description','.content']);
      const teacher=text(row,['.teacher','.publisher']);
      const submission=text(row,['.submission-method','.submit-method']);
      const status=text(row,['.status','.state']);
      let taskType=row.dataset.taskKind||options.taskType||(/考试|测验/.test(title)?'exam':/实验/.test(title)?'experiment':/汇报|展示|演讲/.test(title)?'presentation':'assignment');
      if(!['assignment','exam','experiment','project','presentation','other'].includes(taskType))taskType='other';
      const evidence={title};if(deadlineText)evidence.deadline=deadlineText;if(submission)evidence.submission_method=submission;
      if(publishedAt)evidence.published_at=publishedText.slice(0,240);
      const revision=fingerprint([title,course,className,stableTime(deadlineText),description,submission,status].join('\n'));
      const job={kind:'task_center',message_id:'task_'+identity+'_'+fingerprint(url)+'_'+revision,title,text:description||[title,deadlineText,submission,status].filter(Boolean).join('；'),description,course,conversation:className||course,sender:teacher,display_time:'',captured_at:new Date().toISOString(),published_at:publishedAt,direction:'received',task_type:taskType,deadline:deadline(deadlineText),submission_method:submission,platform_status:status,teacher,url,field_evidence:evidence};
      // Use an actual link provided by the row; never invent a view URL from task.
      const links=[row.getAttribute('data-detail-url'),row.getAttribute('data-readonly-url'),...[...row.querySelectorAll('a[href]')].map(a=>a.getAttribute('href'))];
      for(const link of links){if(!link)continue;const candidate=official(link,base);if(candidate&&sameTask(job.url,candidate)&&detailUrl({...job,detail_url:'',url:candidate})){job.detail_url=candidate;break}}
      return job;
    }).filter(Boolean);
  }
  // Only explicitly read-only routes may be followed by the background collector.
  function detailUrl(job){
    if(job.task_type==='exam')return '';
    for(const raw of [job.detail_url,job.url]){
      const value=raw&&official(raw);if(!value||!sameTask(job.url,value))continue;
      const u=new URL(value);
      if([...u.searchParams.keys()].some(k=>/answer|submit|start|save|begin|doexam/i.test(k)))continue;
      if(/^\/(?:mooc-ans\/)?(?:mooc2\/)?work\/(?:view|detail)$/.test(u.pathname))return value;
    }
    return '';
  }
  function sameTask(left,right){
    try{
      const ids=value=>{const u=new URL(value),p=new Map();for(let [k,v] of u.searchParams){k=k.toLowerCase().replace(/[_-]/g,'');if(k==='clazzid')k='classid';if(!['courseid','classid','workid','id'].includes(k))continue;if(/^\d+$/.test(v))v=BigInt(v).toString();if(p.has(k)&&p.get(k)!==v)return [];p.set(k,v)}if(p.has('workid')&&p.has('id')&&p.get('workid')!==p.get('id'))return [];return [p.get('courseid'),p.get('classid'),p.get('workid')||p.get('id')]};
      const a=ids(left),b=ids(right);return a.length===3&&b.length===3&&a.every(v=>/^[A-Za-z0-9_-]{1,80}$/.test(v||''))&&a.every((v,i)=>v===b[i]);
    }catch{return false}
  }
  // Static HTML fetching only. Never use this URL validator for browser navigation.
  function assignmentContentUrl(job){
    if(job.task_type==='exam')return '';
    const value=official(job.url);if(!value||!sameTask(value,value))return '';
    const u=new URL(value);
    if(!/^\/(?:mooc-ans\/)?(?:mooc2\/)?work\/(?:task|dowork|view|detail)$/.test(u.pathname))return '';
    if([...u.searchParams.keys()].some(k=>!/^(?:answerId|workAnswerId)$/i.test(k)&&/answer|submit|start|save|begin|exam/i.test(k)))return '';
    return value;
  }
  // Discover original files independently of formats that can yield text.
  function attachmentFiles(containers,visible){
    const attachments=[],names=[],seen=new Set(),nodes=new Set();let pending=0;
    const doc=containers[0]?.ownerDocument;
    const restricted=doc&&[...doc.scripts].some(s=>/\bATTACH__NO_DOWNLOAD_PATH\s*=\s*['"][^'"]+['"]/.test(s.textContent||''))&&!['1','true'].includes(doc.querySelector('#allowDownloadAttachment')?.value||'');
    for(const container of containers)for(const node of container.querySelectorAll('a.attachment,a[data-attachment],.attachNew,.workAttach,.attachments a,iframe.attach-iframe,iframe.attach-insertCloud[name]')){
      if(nodes.has(node)||!visible(node)||node.closest('.stem_answer,.mark_answer,.stuAnswerContent'))continue;
      // Nested links belong to the enclosing file widget.
      if(node.parentElement?.closest('.attachNew,.workAttach'))continue;
      nodes.add(node);let name='',href='',size=0;
      if(node.tagName==='IFRAME'){
        try{
          const data=JSON.parse(decodeURIComponent(atob(node.getAttribute('name')||''))),file=data.att_clouddisk||data;
          name=file.name||file.infoJsonStr?.name||'';size=Number.isSafeInteger(file.size)&&file.size>=0?file.size:0;
          href=file.downPath||(/^[a-fA-F0-9]{32}$/.test(file.objectid||'')?'https://d0.cldisk.com/download/'+file.objectid:'');
        }catch{}
      }else{
        const meta=node.matches('[data][name]')?node:node.querySelector('[data][name]');
        name=meta?.getAttribute('name')||node.getAttribute('download')||node.querySelector('[name]')?.getAttribute('name')||node.innerText||node.textContent||'';
        href=node.getAttribute('href')||node.querySelector('a[href]')?.getAttribute('href')||'';
        if(!/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(href)&&/^[a-fA-F0-9]{32}$/.test(meta?.getAttribute('data')||''))href='https://d0.cldisk.com/download/'+meta.getAttribute('data');
      }
      name=String(name).trim().slice(0,180);if(name&&!names.includes(name))names.push(name);
      if(!restricted&&name&&/^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(href)){
        if(seen.has(href))continue;seen.add(href);
        if(attachments.length<20){attachments.push({name,url:href,size,status:'listed'});continue}
      }
      pending++;
    }
    return {attachments,names,pending,nodes};
  }
  function enrichAssignment(doc,url,job){
    const missing={...job,detail_state:'unavailable',detail_error:'作业正文或任务身份未核对，保留列表信息。'};
    if(!assignmentContentUrl({...job,url})||!sameTask(job.url,url))return {...missing,detail_error:'作业正文入口身份未核对，保留列表信息。'};
    const container=doc.querySelector('.fanyaMarking');if(!container)return missing;
    // aria-hidden on the official question heading controls accessibility only.
    // It is still rendered; actual hidden/display:none content stays excluded.
    const visible=n=>!n.closest('[hidden]')&&(!doc.defaultView||(n.getClientRects().length>0&&doc.defaultView.getComputedStyle(n).visibility!=='hidden'));
    const title=container.querySelector('.detailsHead .mark_title');
    if(!title||!visible(title)||title.textContent.trim().replace(/\s/g,'')!==job.title.replace(/\s/g,''))return {...missing,detail_error:'作业正文标题与列表不一致，保留列表信息。'};
    const params=new Map([...new URL(job.url).searchParams].map(([k,v])=>[k.toLowerCase(),v.replace(/^0+(?=\d)/,'')]));
    for(const [selector,id] of [['#courseId','courseid'],['#classId','classid'],['#workRelationId','workid']]){
      const value=doc.querySelector(selector)?.value;
      if(value&&params.has(id)&&value.replace(/^0+(?=\d)/,'')!==params.get(id))return {...missing,detail_error:'作业正文课程或班级身份不一致，保留列表信息。'};
    }
    const stems=[...container.querySelectorAll('.mark_table .mark_name')].filter(visible);
    if(!stems.length)return {...missing,detail_error:'作业题目尚未加载，保留列表信息。'};
    const description=stems.map(n=>{const copy=n.cloneNode(true);for(const el of copy.querySelectorAll('script,style,textarea,input,button,[hidden],[aria-hidden="true"],.stem_answer,.mark_answer,.stuAnswerContent'))el.remove();return (copy.innerText||copy.textContent||'').trim()}).filter(Boolean).join('\n\n');
    const headers=[...container.querySelectorAll('.detailsHead .infoHead p')].filter(visible).map(n=>n.textContent.trim());
    const due=headers.find(s=>/作答时间|截止|结束/.test(s)&&/至|截止|结束/.test(s))||'';
    const parsed=deadline(due),evidence={...job.field_evidence};if(due)evidence.deadline=due.slice(0,240);
    const files=attachmentFiles(stems,visible),attachments=files.attachments,seen=new Set(attachments.map(a=>a.url)),fileNames=files.names;let pending=files.pending;
    // Count media only in question stems, excluding personal answers and UI icons.
    for(const n of stems)for(const el of n.querySelectorAll('img,video,audio,canvas,object,embed,iframe')){
      if(!visible(el)||el.closest('.attachNew,.workAttach')||files.nodes.has(el))continue;
      let image='';
      try{const u=new URL(el.getAttribute('src')||'',url);if(el.tagName==='IMG'&&['http:','https:'].includes(u.protocol)&&u.hostname==='p.ananas.chaoxing.com'&&!u.port&&!u.username&&!u.password&&/\.(png|jpe?g|bmp|webp)$/i.test(u.pathname)){u.protocol='https:';u.hash='';image=u.href}}catch{}
      if(image&&seen.has(image))continue;
      if(image&&attachments.length<20){seen.add(image);attachments.push({name:'作业图片'+(attachments.length+1)+new URL(image).pathname.match(/\.[a-z0-9]+$/i)[0].toLowerCase(),url:image,kind:'inline_image',status:'listed'})}
      else pending++;
    }
    const warnings=[];
    if(due&&!parsed&&!job.deadline)warnings.push('作答时间未包含完整年份，截止时间请核对原文。');
    if(pending)warnings.push('作业中有图片或附件尚未读取，请打开原任务核对。');
    if(!description&&!fileNames.length&&!pending)return missing;
    const content=[description,...headers,...fileNames.map(n=>'附件：'+n)].filter(Boolean).join('\n');
    if(content.length>28000)warnings.push('作业正文超出读取长度，请打开原任务核对。');
    return {...job,description:description.slice(0,2000),text:[stableTime(job.text),content].filter(Boolean).join('\n').slice(0,30000),deadline:parsed||job.deadline||null,published_at:job.published_at||null,field_evidence:evidence,attachments,media_pending_count:Math.min(1000,pending),detail_state:content.length>28000?'unavailable':'read',detail_error:warnings.join(''),message_id:job.message_id+'_a'+fingerprint(content)};
  }
  function enrichDetail(doc,url,job){
    const missing={...job,detail_state:'unavailable',detail_error:'作业详情结构或任务身份未核对，保留列表信息。'};
    if(!detailUrl({...job,detail_url:'',url})||!sameTask(job.url,url))return missing;
    const container=doc.querySelector('.work-details,.workDetail,.work-detail,[data-work-detail]');
    if(!container)return missing;
    const visible=node=>node&&!node.closest('[hidden],[aria-hidden="true"]')&&(!doc.defaultView||node.getClientRects().length>0);
    const read=selectors=>{for(const selector of selectors)for(const n of container.querySelectorAll(selector)){if(visible(n)){const value=(n.innerText||n.textContent||'').trim();if(value)return value}}return ''};
    const title=read(['.work-title','h1','h2']);
    if(title&&title.replace(/\s/g,'')!==job.title.replace(/\s/g,''))return missing;
    const description=read(['.work-description','.work-instructions','.instructions','[data-task-description]']);
    const due=read(['.deadline','.end-time','.work-time']),submission=read(['.submission-method','.submit-method']);
    const publishedText=publicationText(container),publishedAt=publication(publishedText);
    const status=read(['.status','.state']);
    const files=attachmentFiles([container],visible),attachments=files.attachments,unread=files.pending;
    if(!description&&!attachments.length)return missing;
    const evidence={...job.field_evidence};if(due)evidence.deadline=due.slice(0,240);if(submission)evidence.submission_method=submission.slice(0,240);
    if(publishedAt)evidence.published_at=publishedText.slice(0,240);
    const result={...job,description:(description||job.description||'').slice(0,2000),deadline:deadline(due)||job.deadline,submission_method:(submission||job.submission_method||'').slice(0,160),platform_status:(status||job.platform_status||'').slice(0,100),field_evidence:evidence,attachments,detail_state:'read',detail_error:''};
    if(unread){result.media_pending_count=Math.min(1000,unread);result.detail_error='说明中有未支持或超出读取数量的附件，请打开原任务核对。'}
    result.published_at=publishedAt||job.published_at||null;
    result.text=[job.text,description,due,submission,status,...attachments.map(a=>'附件：'+a.name)].filter(Boolean).join('\n').slice(0,30000);
    result.message_id=job.message_id+'_d'+fingerprint(JSON.stringify([description,stableTime(due),submission,status,attachments]));
    return result;
  }
  root.CourseInboxTasks={extractDocument,detailUrl,enrichDetail,sameTask,assignmentContentUrl,enrichAssignment};
  if(typeof module!=='undefined')module.exports=root.CourseInboxTasks;
})(typeof globalThis!=='undefined'?globalThis:this);
