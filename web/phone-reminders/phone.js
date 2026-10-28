'use strict';
(() => {
  const KEY='courseinbox.phone-reminders.v1',$=id=>document.getElementById(id);
  let state={session:null,history:[],pending:[],enabled:false,sound:false,control:''},generation=0,timer,busy=false,controller,audio;
  const validId=value=>typeof value==='string'&&/^[0-9a-f]{32}$/.test(value);
  const eventId=value=>typeof value==='string'&&/^[A-Za-z0-9:_.-]{1,200}$/.test(value);
  const eventValid=e=>e&&eventId(e.id)&&typeof e.title==='string'&&e.title.length<=300&&typeof e.body==='string'&&e.body.length<=20000;
  const sessionValid=s=>s&&validId(s.server_id)&&validId(s.device_id)&&typeof s.token==='string'&&/^[A-Za-z0-9_-]{24,100}$/.test(s.token);
  function notice(text=''){ $('notice').textContent=text;$('notice').hidden=!text; }
  function decode(value){return {session:sessionValid(value.session)?value.session:null,history:Array.isArray(value.history)?value.history.filter(eventValid).slice(0,100):[],pending:Array.isArray(value.pending)?value.pending.filter(eventId).slice(0,200):[],enabled:value.enabled===true,sound:value.sound===true,control:typeof value.control==='string'?value.control:''};}
  function sharedControl(){try{return JSON.parse(localStorage.getItem(KEY)||'{}').control||'';}catch{return null;}}
  function save(control=false){
    if(control)state.control=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
    else if(sharedControl()!==state.control)throw new Error('连接设置已在另一个页面改变。');
    localStorage.setItem(KEY,JSON.stringify(state));
  }
  function storageReady(){try{localStorage.setItem(KEY+'.test','1');localStorage.removeItem(KEY+'.test');return true;}catch{notice('此浏览器无法保存配对与提醒，请允许网站存储后重试。');return false;}}
  try{const value=JSON.parse(localStorage.getItem(KEY)||'null');if(value)state=decode(value);}catch{notice('未能读取配对，请重新连接电脑。');}
  function paint(){
    window.CampusInboxPush?.refresh();
    $('pairForm').hidden=!!state.session;$('toggleReceive').hidden=$('disconnect').hidden=!state.session;
    $('toggleReceive').textContent=state.enabled?'停止接收':'恢复接收';$('soundToggle').textContent='提示音：'+(state.sound?'开':'关');
    const history=$('history');history.replaceChildren();
    if(!state.history.length){const p=document.createElement('p');p.className='empty';p.textContent='连接后，新提醒会显示在这里。';history.append(p);}
    for(const event of state.history){const card=document.createElement('article'),title=document.createElement('h3'),body=document.createElement('p');card.className='event';title.textContent=event.title;body.textContent=event.body;card.append(title,body);history.append(card);}
  }
  function status(text){$('connectionStatus').textContent=text;}
  function cancel(){generation++;clearTimeout(timer);controller?.abort();busy=false;$('connect').disabled=false;$('connect').removeAttribute('aria-busy');$('connect').textContent='连接电脑';}
  async function request(path,body,token,signal){
    const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(token?{Authorization:'Bearer '+token}:{})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',redirect:'error',credentials:'omit',signal});
    if(!response.ok){const error=new Error(response.status===530?'HTTPS 隧道已断开，请在电脑重新运行“启动手机后台提醒”，并使用检查成功后的新地址。':response.status===401?'电脑已撤销配对，请重新连接。':response.status===400?'配对码无效、已使用或已过期，请在电脑重新生成。':location.protocol==='https:'?'HTTPS 提醒入口暂不可达，请检查电脑项目和隧道是否仍在运行。':'电脑连接失败，请检查同一 Wi-Fi 和电脑提醒服务。');error.status=response.status;throw error;}
    return response.json();
  }
  function sound(){if(!state.sound)return;try{const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)return;audio=audio||new Audio();audio.resume().catch(()=>{});const oscillator=audio.createOscillator(),gain=audio.createGain();oscillator.frequency.value=720;gain.gain.value=.08;oscillator.connect(gain);gain.connect(audio.destination);oscillator.start();oscillator.stop(audio.currentTime+.15);}catch{}}
  async function poll(){
    if(busy||!state.enabled||!state.session||document.hidden)return;
    const current=generation,session={...state.session};busy=true;const abort=new AbortController();controller=abort;
    const timeout=setTimeout(()=>abort.abort(),10000);let idle,reader;
    const active=()=>current===generation&&state.enabled&&state.session?.device_id===session.device_id&&sharedControl()===state.control;
    async function accept(batch){
      if(!active()||document.hidden)return;
      if(batch.error==='revoked'){const error=new Error('电脑已撤销配对，请重新连接。');error.status=401;throw error;}
      if(batch.server_id!==session.server_id){const error=new Error('电脑身份已变化，请重新配对。');error.identity=true;throw error;}
      if(!batch.enabled){status('电脑已暂停提醒');return;}
      if(!Array.isArray(batch.events)||batch.events.length>200||!batch.events.every(eventValid))throw new Error('电脑提醒格式不正确，尚未确认接收。');
      const seen=new Set([...state.history.map(e=>e.id),...state.pending]),fresh=[];
      for(const event of batch.events){if(!seen.has(event.id)){fresh.push({id:event.id,title:event.title,body:event.body});seen.add(event.id);}}
      const before=state;
      state={...state,history:[...fresh.reverse(),...state.history].slice(0,100),pending:[...new Set([...state.pending,...batch.events.map(e=>e.id)])]};
      try{if(batch.events.length)save();}catch{state=before;throw new Error('浏览器无法保存提醒或连接已在另一页面改变，尚未确认接收。');}
      paint();if(fresh.length){document.title='('+fresh.length+') CampusInbox · 手机提醒';notice('收到 '+fresh.length+' 条新提醒');sound();}
      if(!active()||document.hidden)return;
      const ids=state.pending.slice(0,100);
      if(ids.length){const result=await request('/v1/ack',{ids},session.token,abort.signal);if(!active())return;if(!result.ok)throw new Error('回执未确认，稍后自动重试。');state.pending=state.pending.filter(id=>!ids.includes(id));save();}
      status('已连接 · 实时推送');
    }
    try{
      const health=await request('/v1/health',undefined,null,abort.signal);if(!active())return;
      if(health.app!=='CourseInbox Reminders'||health.version!==1||health.server_id!==session.server_id){const error=new Error('电脑身份已变化，请重新配对。');error.identity=true;throw error;}
      // Quick HTTPS tunnels do not support SSE; background delivery uses Web Push.
      if(location.hostname.endsWith('.trycloudflare.com')){await accept(await request('/v1/alerts',undefined,session.token,abort.signal));return;}
      const response=await fetch('/v1/stream',{headers:{Authorization:'Bearer '+session.token},cache:'no-store',redirect:'error',credentials:'omit',signal:abort.signal});
      if(!response.ok){const error=new Error('推送连接失败，请检查电脑提醒服务。');error.status=response.status;throw error;}
      if(!response.headers.get('Content-Type')?.startsWith('text/event-stream'))throw new Error('电脑推送服务不兼容，请刷新页面。');
      clearTimeout(timeout);reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
      while(active()&&!document.hidden){
        clearTimeout(idle);idle=setTimeout(()=>abort.abort(),45000);
        const {value,done}=await reader.read();if(done)throw new Error('推送连接中断，正在重连。');
        if(!active()||document.hidden)return;
        buffer+=decoder.decode(value,{stream:true});if(buffer.length>1024*1024)throw new Error('推送数据过大，尚未确认接收。');
        let boundary;
        while((boundary=buffer.indexOf('\n\n'))>=0){
          const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
          const data=frame.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
          if(data)await accept(JSON.parse(data));
        }
      }
    }catch(error){
      if(!active())return;
      if(error.status===401||error.identity){state={...state,session:null,enabled:false,pending:[]};try{save(true);}catch{}paint();status('配对已失效');notice(error.message);}
      else{status('暂未连接 · 稍后自动重连');notice(error.name==='AbortError'?'推送连接超时，正在重连。':error.message);}
    }finally{
      clearTimeout(timeout);clearTimeout(idle);abort.abort();reader?.cancel().catch(()=>{});
      if(current===generation){busy=false;if(state.enabled&&!document.hidden)timer=setTimeout(poll,5000);}
    }
  }
  $('pairForm').addEventListener('submit',async event=>{
    event.preventDefault();if(!storageReady())return;const code=$('pairCode').value.trim(),name=$('phoneName').value.trim();if(!/^[0-9]{6}$/.test(code)||!name||name.length>80){notice('请填写六位配对码和手机名称。');return;}
    cancel();state.enabled=false;try{save(true);}catch{notice('无法保存连接状态，请检查浏览器存储。');return;}const current=generation,pairControl=state.control,active=()=>current===generation&&sharedControl()===pairControl;$('connect').disabled=true;$('connect').setAttribute('aria-busy','true');$('connect').textContent='正在连接…';notice();status('正在连接电脑…');sound();const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),10000);controller=abort;
    try{const health=await request('/v1/health',undefined,null,abort.signal);if(!active())return;if(health.app!=='CourseInbox Reminders'||health.version!==1||!validId(health.server_id))throw new Error('电脑提醒服务不兼容。');
      const paired=await request('/v1/pair',{code,name},null,abort.signal);if(!active())return;if(!sessionValid(paired)||paired.server_id!==health.server_id)throw new Error('配对时电脑身份变化，请重新生成配对码。');
      state={...state,session:paired,enabled:true,pending:[]};save(true);$('pairCode').value='';paint();status('配对成功，正在接收…');poll();
    }catch(error){if(current===generation){status('尚未连接');notice(error.name==='AbortError'?'连接超时，请检查电脑提醒服务。':error.message);}}
    finally{clearTimeout(timeout);if(current===generation){$('connect').disabled=false;$('connect').removeAttribute('aria-busy');$('connect').textContent='连接电脑';}}
  });
  $('toggleReceive').addEventListener('click',async()=>{if(state.enabled)await window.CampusInboxPush?.stop();cancel();state.enabled=!state.enabled;try{save(true);}catch{state.enabled=false;notice('无法保存状态，请检查浏览器存储。');}paint();status(state.enabled?'正在恢复接收…':'已停止接收');if(state.enabled){sound();poll();}});
  $('disconnect').addEventListener('click',async()=>{await window.CampusInboxPush?.stop();cancel();state={...state,session:null,enabled:false,pending:[]};try{save(true);}catch{notice('无法保存断开状态，请在电脑撤销此设备。');}paint();status('已断开 · 提醒记录保留');$('connect').disabled=false;});
  $('soundToggle').addEventListener('click',()=>{state.sound=!state.sound;try{save(true);}catch{notice('无法保存提示音设置。');}paint();sound();});
  window.addEventListener('storage',event=>{if(event.key!==KEY)return;try{const next=event.newValue?decode(JSON.parse(event.newValue)):{...state,session:null,enabled:false,pending:[],control:''};const changed=next.control!==state.control;if(changed)cancel();state=next;paint();if(changed){$('connect').disabled=false;status(state.session?(state.enabled?'正在恢复连接…':'已停止接收'):'已断开配对');if(state.enabled&&state.session)poll();}}catch{cancel();state.enabled=false;status('连接设置无法读取，请重新配对');}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){document.title='CampusInbox · 手机提醒';clearTimeout(timer);poll();}else{cancel();status(state.enabled?'网页已在后台 · 返回后补收':'已停止接收');}});
  paint();status(state.session?(state.enabled?'正在恢复连接…':'已停止接收'):'尚未配对');if(state.session&&state.enabled)poll();
})();
