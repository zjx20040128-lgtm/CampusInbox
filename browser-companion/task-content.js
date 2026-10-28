(()=>{
  'use strict';
  const accepted=new Map();let scheduled,scanning=false;
  async function scan(){
    if(scanning)return;scanning=true;
    try{
      const state=await chrome.runtime.sendMessage({type:'sync-state'});if(!state?.enabled)return;
      const messages=CourseInboxTasks.extractDocument(document,location.href).filter(item=>!accepted.has(item.message_id)||Date.now()-accepted.get(item.message_id)>=60000);
      if(!messages.length)return;
      const result=await chrome.runtime.sendMessage({type:'capture',messages});for(const id of result?.accepted||[])accepted.set(id,Date.now());
      if(accepted.size>10000)accepted.clear();
    }catch{/* A later page mutation or retry alarm will try again. */}finally{scanning=false}
  }
  function schedule(){clearTimeout(scheduled);scheduled=setTimeout(scan,800)}
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,characterData:true});
  setInterval(scan,15000);scan();
})();
