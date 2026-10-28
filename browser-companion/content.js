(() => {
  if(location.hash==='#courseinbox-refresh')return;
  const accepted=new Set();
  const noticePage=location.origin==='https://notice.chaoxing.com';
  let scheduled,scanning=false,lastListFetch=Date.now();
  async function enabled() {return (await chrome.runtime.sendMessage({type:'sync-state'}))?.enabled===true}
  async function report(error='') {await chrome.runtime.sendMessage({type:'source-status',error})}
  async function getHTML(url) {
    const response=await fetch(url,{credentials:'same-origin',signal:AbortSignal.timeout(10000)});
    if(!response.ok || new URL(response.url).origin!==location.origin || !new URL(response.url).pathname.startsWith('/pc/notice/'))throw new Error('学习通登录可能已失效，请重新登录并打开收件箱。');
    const text=await response.text();if(text.length>2000000)throw new Error('通知页面过大，请打开通知详情同步。');
    return new DOMParser().parseFromString(text,'text/html');
  }
  async function refreshedList() {
    // Use the site's rendered page: some deployments populate rows with JavaScript.
    const frame=document.createElement('iframe');frame.hidden=true;frame.setAttribute('aria-hidden','true');
    const url=new URL(location.href);url.hash='courseinbox-refresh';frame.src=url.href;
    try {
      await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('通知列表刷新超时，请检查学习通登录。')),10000);frame.onload=()=>{clearTimeout(timer);resolve()};frame.onerror=()=>{clearTimeout(timer);reject(new Error('通知列表未加载。'))};document.body.append(frame)});
      for(let i=0;i<10;i++) {
        if(!await enabled())return [];
        const doc=frame.contentDocument;if(!doc)throw new Error('学习通登录可能已失效，请重新打开收件箱。');
        const rows=CourseInboxNotices.extractList(doc,location.href);if(rows.length)return rows;
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      await report('刷新后的通知列表为空；请检查登录或在学习通收件箱刷新。');return [];
    } finally{frame.remove()}
  }
  async function collectNotices() {
    const parser=CourseInboxNotices;
    if(/\/detail$/.test(location.pathname)) {
      const job=parser.extractDetail(document,{url:location.href});return job && !accepted.has(job.message_id)?[job]:[];
    }
    let rows=parser.extractList(document,location.href);
    if(Date.now()-lastListFetch>=60000) {rows=await refreshedList();lastListFetch=Date.now()}
    const jobs=[];let tried=0,failed=false;
    for(const row of rows) {
      const key=parser.noticeFromFields({...row,text:'identity'})?.message_id;
      if(!key || accepted.has(key))continue;
      if(tried++>=25 || !await enabled())break;
      try {
        const job=parser.extractDetail(await getHTML(row.url),row);
        if(job)jobs.push(job);else {failed=true;await report('未找到完整通知正文，请打开该通知详情核对。')}
      } catch(error) {failed=true;await report(error.message)}
    }
    if(!failed && rows.length)await report();
    return jobs;
  }
  async function scan() {
    if(scanning)return;scanning=true;
    try {
      if(!await enabled())return;
      const messages=noticePage?await collectNotices():CourseInboxChaoxing.extractDocument(document).filter(m=>!accepted.has(m.message_id)).slice(0,100);
      if(!messages.length)return;
      const result=await chrome.runtime.sendMessage({type:'capture',messages});
      for(const id of result?.accepted||[])accepted.add(id);
      if(accepted.size>10000)accepted.clear();
    } catch(error) {try{await report(error.message)}catch{/* Extension may have been reloaded. */}}
    finally{scanning=false}
  }
  function schedule(){clearTimeout(scheduled);scheduled=setTimeout(scan,800)}
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,characterData:true});
  setInterval(scan,15000);scan();
})();
