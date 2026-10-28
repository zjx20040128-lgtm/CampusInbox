'use strict';
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('push',event=>event.waitUntil((async()=>{
 let value;try{value=event.data.json()}catch{return}
 if(!value||typeof value.id!=='string'||typeof value.title!=='string'||typeof value.body!=='string')return;
 await self.registration.showNotification(value.title.slice(0,120),{body:value.body.slice(0,400),tag:value.id,icon:'/icon.svg',data:{url:'/'}});
 const clients=await self.clients.matchAll({type:'window',includeUncontrolled:true});
 for(const client of clients)client.postMessage({type:'campusinbox-push',event:value});
})()));
self.addEventListener('notificationclick',event=>{
 event.notification.close();event.waitUntil((async()=>{
  const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  for(const client of windows)if(new URL(client.url).origin===self.location.origin)return client.focus();
  return self.clients.openWindow('/');
 })());
});
