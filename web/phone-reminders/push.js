'use strict';
(()=>{
 const button=document.getElementById('backgroundPush'),hint=document.getElementById('pushHint');
 const read=()=>{try{return JSON.parse(localStorage.getItem('courseinbox.phone-reminders.v1')||'{}')}catch{return {}}};
 async function request(path,body,session=read().session){
  if(!session)throw Error('请先输入配对码连接电脑。');
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+session.token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',credentials:'omit',redirect:'error'});
  if(!response.ok)throw Error(response.status===401?'配对已撤销，请重新连接。':'后台提醒设置失败，请检查电脑服务。');return response.json();
 }
 const supported=window.isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
 let busy=false;
 async function refresh(){
  button.hidden=!read().session;button.disabled=busy;
  if(!supported){button.disabled=true;hint.textContent=location.protocol==='http:'?'后台提醒需要 HTTPS 地址；当前仍可在页面内接收。':'当前浏览器不支持后台网页推送，请换用支持 Web Push 的浏览器。';return}
  const registration=await navigator.serviceWorker.getRegistration();const sub=await registration?.pushManager.getSubscription();
  button.textContent=sub?'关闭后台提醒':'开启后台提醒';
  hint.textContent=sub?'后台提醒已开启；可以关闭页面。浏览器需允许通知和后台运行。':'首次点击授权通知，随后可以关闭页面接收。';
 }
 async function stop(){
  const session=read().session,registration=await navigator.serviceWorker?.getRegistration(),sub=await registration?.pushManager.getSubscription();
  try{if(session)await request('/v1/push/unsubscribe',{},session)}finally{await sub?.unsubscribe();await refresh()}
 }
 button.addEventListener('click',async()=>{
  if(busy)return;busy=true;button.disabled=true;
  try{
   if(!supported)throw Error('请从 HTTPS 地址打开提醒页面。');
   if(!read().enabled)throw Error('请先恢复接收提醒。');
   const existing=await navigator.serviceWorker.getRegistration(),old=await existing?.pushManager.getSubscription();
   if(old){await stop();return}
   if(await Notification.requestPermission()!=='granted')throw Error('通知未授权，请在浏览器网站设置中允许通知。');
   await navigator.serviceWorker.register('/sw.js',{scope:'/'});const registration=await navigator.serviceWorker.ready;
   const {public_key}=await request('/v1/push/key');
   const raw=atob(public_key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-public_key.length%4)%4));
   const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:Uint8Array.from(raw,c=>c.charCodeAt(0))});
   try{await request('/v1/push/subscribe',subscription.toJSON())}catch(error){await subscription.unsubscribe();throw error}
  }catch(error){hint.textContent=error.message;return}
  finally{busy=false;button.disabled=false}
  await refresh();
 });
 window.CampusInboxPush={refresh:()=>refresh().catch(()=>{}),stop:()=>stop().catch(error=>{hint.textContent=error.message})};
 navigator.serviceWorker?.addEventListener('message',message=>{if(message.data?.type==='campusinbox-push')window.dispatchEvent(new CustomEvent('campusinbox-push',{detail:message.data.event}))});
 window.addEventListener('storage',()=>refresh().catch(()=>{}));refresh().catch(()=>{});
})();
