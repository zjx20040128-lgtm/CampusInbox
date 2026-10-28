(function(root) {
  'use strict';
  const timeParser=typeof module!=='undefined' && module.exports ? require('./parser.js') : root.CourseInboxChaoxing;
  function safeDetailURL(value, base) {
    try {const u=new URL(value,base);if(u.origin!=='https://notice.chaoxing.com' || !/^\/pc\/notice\/[^/]+\/detail$/.test(u.pathname))return null;u.search='';u.hash='';return u.href} catch{return null}
  }
  function safeAttachmentURL(value) {return /^https:\/\/d0\.cldisk\.com\/download\/[a-fA-F0-9]{32}$/.test(value||'')?value:''}
  function safeImageURL(value) {
    try{const u=new URL(value);if(u.hostname!=='p.ananas.chaoxing.com'||u.username||u.password||u.port||!/^https?:$/.test(u.protocol)||!/\.(?:png|jpe?g|bmp|webp)$/i.test(u.pathname))return '';u.protocol='https:';u.hash='';return u.href}catch{return ''}
  }
  function mediaEvidence(content) {
    const nodes=Array.from(content.querySelectorAll('img,video,audio,canvas,object,embed,iframe:not(.attach-insertCloud)')).filter(node=>!node.closest('.attach-module'));
    const attachments=[];const seen=new Set();let pending=0;
    for(const node of nodes){
      const url=node.tagName==='IMG'?safeImageURL(node.getAttribute('src')||''):'';
      if(!url){pending++;continue}
      if(seen.has(url))continue;
      if(attachments.length>=20){pending++;continue}
      seen.add(url);const suffix=new URL(url).pathname.match(/\.[a-z0-9]+$/i)[0].toLowerCase();
      attachments.push({name:'通知图片'+(attachments.length+1)+suffix,url,size:0,status:'listed',kind:'inline_image'});
    }
    return {attachments,pending};
  }
  function detailDataURL(value) {
    const detail=safeDetailURL(value);if(!detail)return null;
    const url=new URL(detail);url.pathname=url.pathname.replace(/\/detail$/,'/getNoticeDetail');url.search='?sendTag=0';return url.href;
  }
  function attachmentFromFrame(frame) {
    try {
      const data=JSON.parse(decodeURIComponent(atob(frame.getAttribute('name')||''))).att_clouddisk;
      const name=(data.name||data.infoJsonStr?.name||'').trim();if(!name || name.length>180)return null;
      return {name,url:safeAttachmentURL(data.downPath),size:Number.isSafeInteger(data.size)&&data.size>=0?data.size:0,status:'listed'};
    } catch{return null}
  }
  function noticeFromFields(fields,now=new Date()) {
    const url=safeDetailURL(fields.url),id=url?.split('/')[5]?.replace(/^\$[A-Z]+\$/,'');
    const title=(fields.title||'').trim(),text=(fields.text||'').trim();
    const attachments=(fields.attachments||[]).slice(0,20).map(a=>({name:a.name,url:a.kind==='inline_image'?safeImageURL(a.url):safeAttachmentURL(a.url),size:a.size||0,status:'listed',...(a.kind==='inline_image'?{kind:'inline_image'}:{})}));
    if(!id || !/^[A-Za-z0-9_-]{1,180}$/.test(id) || !title || title.length>160 || (!text&&!attachments.length&&fields.empty_body_ready!==true&&!(fields.media_pending_count>0)) || text.length>28000)return null;
    const course=title.match(/《([^》]+)》/)?.[1]?.slice(0,100)||fields.course||'';
    return {kind:'course_notice',message_id:'notice_'+id,title,text,course,conversation:course,
      sender:(fields.sender||'').trim().slice(0,100),display_time:(fields.time||'').trim().slice(0,100),
      captured_at:timeParser.parseTime(fields.time,now),direction:'received',url,
      attachments,...(Number.isSafeInteger(fields.media_pending_count)?{media_pending_count:fields.media_pending_count}: {})};
  }
  function extractList(doc,base) {
    return Array.from(doc.querySelectorAll('.dataBody_item[data-id]')).flatMap(row=>{
      const open=row.querySelector('.openNotice[data-sendtag="0"]');
      if(!open)return [];
      const url=safeDetailURL(open.getAttribute('data-url'),base);
      const title=row.querySelector('.notice_title')?.textContent?.trim();
      if(!url || !title)return [];
      return [{id:row.getAttribute('data-id'),url,title,time:row.querySelector('.notice_time')?.textContent?.trim()||'',sender:row.querySelector('.receiverName')?.textContent?.trim()||''}];
    });
  }
  function bodyText(element) {
    const clone=element.cloneNode(true);
    clone.querySelectorAll('script,style,iframe,.attach-module').forEach(el=>el.remove());
    clone.querySelectorAll('br').forEach(el=>el.replaceWith('\n'));
    clone.querySelectorAll('p,div,li,tr').forEach(el=>el.append('\n'));
    return (clone.textContent||'').replace(/\n[ \t]+/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
  }
  function extractDetail(doc,row,now=new Date(),options={}) {
    const content=doc.querySelector('.noticeContent');if(!content)return null;
    const headerTitle=doc.querySelector('#title')?.textContent?.trim()||'',published=doc.querySelector('.createTime')?.textContent?.trim()||'',sender=doc.querySelector('.createName')?.textContent?.trim()||'';
    const time=published||row.time||'';
    const captureMedia=options.inlineImages===true,media=captureMedia?mediaEvidence(content):{attachments:[],pending:0},files=Array.from(content.querySelectorAll('iframe.attach-insertCloud[name]')).map(attachmentFromFrame).filter(Boolean);
    return noticeFromFields({...row,title:headerTitle||row.title,
      text:bodyText(content),time,sender:sender||row.sender,
      empty_body_ready:Boolean(headerTitle&&published&&sender&&doc.readyState==='complete'&&!content.querySelector('img,video,audio,canvas,object,embed,iframe')),
      attachments:[...files,...media.attachments],...(captureMedia?{media_pending_count:media.pending+Math.max(0,files.length+media.attachments.length-20)}:{})},now);
  }
  /** The official detail template loads this JSON; parse rich text without executing its scripts. */
  function extractData(doc,response,row,now=new Date(),options={}) {
    const url=safeDetailURL(row.url),data=response?.msg;
    if(!url||response?.status!==true||!data||typeof data!=='object'||Array.isArray(data))return null;
    if(data.uuid!==new URL(url).pathname.split('/')[3]||(row.id&&data.idCode!==row.id))return null;
    if(typeof data.title!=='string')return null;
    const rich=data.isRtf===1||data.isRtf===true;
    const value=rich?data.rtf_content:data.content;
    if(typeof value!=='string'||value.length>2000000)return null;
    const fragment=doc.implementation.createHTMLDocument(''),content=fragment.createElement('div');
    if(rich)content.innerHTML=value;else content.textContent=value;
    const captureMedia=options.inlineImages===true,media=captureMedia?mediaEvidence(content):{attachments:[],pending:0},files=Array.from(content.querySelectorAll('iframe.attach-insertCloud[name]')).map(attachmentFromFrame).filter(Boolean);
    const attachments=[...files,...media.attachments];
    const hasMedia=Boolean(content.querySelector('img,video,audio,canvas,object,embed,iframe'))||(!rich&&Boolean(data.imgs?.length||data.attachment?.length));
    const job=noticeFromFields({...row,title:data.title,text:bodyText(content),sender:typeof data.createrName==='string'?data.createrName:row.sender,
      time:typeof data.ftime==='string'?data.ftime:row.time,attachments,...(captureMedia?{media_pending_count:media.pending+Math.max(0,attachments.length-20)+(!rich&&Boolean(data.imgs?.length||data.attachment?.length)?1:0)}:{}),empty_body_ready:!value.trim()&&!hasMedia},now);
    if(job&&Number.isSafeInteger(data.insertTime)&&data.insertTime>=946684800000&&data.insertTime<=now.getTime()+300000)job.captured_at=new Date(data.insertTime).toISOString();
    if(job&&!job.text&&!job.attachments.length&&!job.media_pending_count)job.empty_body_ready=true;
    return job;
  }
  const api={safeDetailURL,safeAttachmentURL,safeImageURL,attachmentFromFrame,noticeFromFields,extractList,extractDetail,detailDataURL,extractData};
  if(typeof module!=='undefined' && module.exports)module.exports=api;else root.CourseInboxNotices=api;
})(typeof globalThis!=='undefined'?globalThis:this);
