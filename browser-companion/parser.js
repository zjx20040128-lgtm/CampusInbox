(function(root) {
  'use strict';
  function parseTime(label, now = new Date()) {
    const cn = new Date(now.getTime() + 8 * 3600000);
    let year=cn.getUTCFullYear(), month=cn.getUTCMonth()+1, day=cn.getUTCDate(), hour, minute;
    let match;
    label=(label||'').trim().replace(/[（(](?:星期|周)[一二三四五六日天][）)]/g,' ').replace(/\s+/g,' ');
    if ((match=label.match(/^(今天\s*)?(\d{1,2}):(\d{2})$/))) {
      hour=+match[2]; minute=+match[3];
    } else if ((match=label.match(/^昨天\s+(\d{1,2}):(\d{2})$/))) {
      const previous=new Date(Date.UTC(year,month-1,day)-86400000);
      year=previous.getUTCFullYear();month=previous.getUTCMonth()+1;day=previous.getUTCDate();
      hour=+match[1];minute=+match[2];
    } else if ((match=label.match(/^(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$/))) {
      if (match[1]) year=+match[1];
      else if (cn.getUTCMonth()<2 && +match[2]>=11) year--;
      month=+match[2];day=+match[3];hour=+match[4];minute=+match[5];
    } else return null;
    const checked=new Date(Date.UTC(year,month-1,day,hour,minute));
    if (checked.getUTCFullYear()!==year || checked.getUTCMonth()+1!==month || checked.getUTCDate()!==day || hour>23 || minute>59) return null;
    if (checked.getTime()-8*3600000 > now.getTime()+5*60000) return null;
    const pad=n=>String(n).padStart(2,'0');
    return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:00+08:00`;
  }
  function messagesFromRows(rows, conversation, now = new Date()) {
    const result=[], seen=new Set();
    let displayTime='';
    if (!conversation || conversation.length>100) return result;
    for (const row of rows) {
      if (row.time!==undefined) {displayTime=row.time;continue}
      const text=(row.text||'').trim(), id=row.id||'';
      if (!/^[A-Za-z0-9_-]{1,200}$/.test(id) || !text || text.length>30000 || seen.has(id)) continue;
      seen.add(id);
      const publication=row.publication_time||displayTime;
      result.push({message_id:id,text,conversation,...(row.activity_type==='checkin'?{activity_type:'checkin'}:{}),sender:(row.sender||'').slice(0,100),
        display_time:publication.slice(0,100),captured_at:parseTime(publication,now),
        direction:row.direction==='sent'?'sent':'received'});
    }
    return result;
  }
  function activityCard(row) {
    // Official webim renders teaching activity cards inside an open ShadowRoot.
    const cards=[];
    for(const host of row.querySelectorAll('attachment-item')) {
      const root=host.shadowRoot;
      const card=(root||host).querySelector('.attach-item[attachment-type="15"]');
      const title=card?.querySelector('.attach-info h1')?.textContent?.trim();
      if(title&&title.length<=160&&/签到/.test(title))cards.push({text:title,time:card.querySelector('.attach-info p')?.textContent?.trim()||''});
    }
    return cards.length===1?cards[0]:null;
  }
  function extractDocument(doc, now = new Date()) {
    const area=doc.querySelector('.message-area');
    const conversation=doc.querySelector('.chat-header .chat-name')?.textContent?.trim();
    if (!area || !conversation) return [];
    const rows=[];
    for(const el of area.children){
      if(el.classList.contains('time-stamp')){rows.push({time:el.textContent.trim()});continue}
      const card=activityCard(el),bubble=el.querySelector('.bubble-text')?.textContent?.trim(),text=bubble||card?.text;
      // A card's own publication label takes precedence and never leaks to later rows.
      rows.push({id:el.getAttribute('data-msg-id'),text,publication_time:card?.time,activity_type:card&&!bubble?'checkin':undefined,
        sender:el.querySelector('.sender-name')?.textContent?.trim(),direction:el.classList.contains('is-other')?'received':'sent'});
    }
    return messagesFromRows(rows,conversation,now);
  }
  const api={parseTime,messagesFromRows,extractDocument,activityCard};
  if (typeof module!=='undefined' && module.exports) module.exports=api;
  else root.CourseInboxChaoxing=api;
})(typeof globalThis!=='undefined'?globalThis:this);
