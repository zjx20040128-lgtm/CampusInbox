/* Presentation only: keep official form nodes, handlers, QR state and verification. */
(function(root){
 'use strict';
 if(location.protocol!=='https:'||location.hostname!=='passport2.chaoxing.com'||!(location.pathname==='/login'||location.pathname.startsWith('/login/'))||location.port&&location.port!=='443')return;
 if(root.CourseInboxMobileLoginUI){root.CourseInboxMobileLoginUI.apply();return;}
 function apply(){
  const card=document.querySelector('.default-login'),left=document.querySelector('#leftdiv'),right=document.querySelector('#rightdiv');
  if(!card||!left||!right||!document.querySelector('#quickCode')||!document.querySelector('#phone')||!document.querySelector('#pwd'))return false;
  if(!document.querySelector('#ci-mobile-login-style')){
   let viewport=document.querySelector('meta[name="viewport"]');
   if(!viewport){viewport=document.createElement('meta');viewport.name='viewport';document.head.appendChild(viewport);}
   viewport.content='width=device-width, initial-scale=1';
   const style=document.createElement('style');style.id='ci-mobile-login-style';
   style.textContent=`
html{height:auto!important;min-width:0!important;background:#f4f6fb}
body[data-ci-mobile-login]{margin:0!important;padding:12px!important;box-sizing:border-box;min-width:0!important;height:auto!important;min-height:100vh;background:#f4f6fb!important;font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif}
body[data-ci-mobile-login] .lg-container{width:100%!important;min-width:0!important;height:auto!important;min-height:0!important}
body[data-ci-mobile-login] .main{box-sizing:border-box;width:100%!important;max-width:420px;min-width:0!important;height:auto!important;min-height:0!important;position:static!important;inset:auto!important;transform:none!important;margin:0 auto!important;padding:0!important}
body[data-ci-mobile-login] .default-login{box-sizing:border-box;width:100%!important;height:auto!important;min-height:0!important;padding:18px 20px 24px!important;display:flex;flex-direction:column;background:white;border-radius:22px;box-shadow:0 8px 30px #273a6510}
body[data-ci-mobile-login] .default-login .lg-top{position:static!important;width:auto!important;float:none!important;text-align:right;font-size:12px;order:-1;margin:2px 0 12px}
body[data-ci-mobile-login] .default-login .lg-top .service{box-sizing:border-box;position:static!important;inset:auto!important;transform:none!important;float:none!important;display:inline-block!important;width:auto!important;height:auto!important;min-height:32px;margin:0!important;padding:6px 10px!important;line-height:20px;font-size:12px!important;border-radius:8px;background:#f6f9ff}
body[data-ci-mobile-login] #leftdiv,body[data-ci-mobile-login] #rightdiv{box-sizing:border-box;position:static!important;inset:auto!important;transform:none!important;float:none!important;width:100%!important;height:auto!important;min-height:0!important;padding:4px 0 0!important;border:0!important}
body[data-ci-login-mode="qr"] #rightdiv{order:1;text-align:center}
body[data-ci-login-mode="qr"] #leftdiv{order:2;padding-top:0!important}
body[data-ci-login-mode="qr"] #leftdiv>.lg-title,body[data-ci-login-mode="qr"] #leftdiv>p:not(.Agreement),body[data-ci-login-mode="qr"] #leftdiv>form,body[data-ci-login-mode="qr"] #leftdiv>.clearaft,body[data-ci-login-mode="qr"] #leftdiv>.line{display:none!important}
body[data-ci-login-mode="account"] #rightdiv{display:none!important}
body[data-ci-mobile-login] .lg-title{font-size:20px!important;line-height:1.4;margin:0 0 20px!important}
body[data-ci-mobile-login] #leftdiv .lg-item{box-sizing:border-box;width:100%!important;height:52px!important;margin-bottom:16px!important}
body[data-ci-mobile-login] #phone,body[data-ci-mobile-login] #pwd{box-sizing:border-box;width:100%!important;height:52px!important;font-size:16px!important;border-radius:14px}
body[data-ci-mobile-login] #phone{padding-right:16px!important}
body[data-ci-mobile-login] #loginBtn{width:100%!important;min-height:52px!important;font-size:17px!important;border-radius:14px!important;margin:24px 0 18px!important}
body[data-ci-mobile-login] #leftdiv>.clearaft{display:flex;flex-wrap:wrap;gap:10px;line-height:1.8}
body[data-ci-mobile-login] #leftdiv>.clearaft .fl,body[data-ci-mobile-login] #leftdiv>.clearaft .fr{float:none!important}
body[data-ci-mobile-login] .ecode-box{box-sizing:border-box;width:240px!important;height:240px!important;max-width:100%;padding:0!important;margin:8px auto 20px!important;border:1px solid #e8edf6;border-radius:18px;position:relative!important}
body[data-ci-mobile-login] #quickCode{box-sizing:border-box;display:block;width:100%!important;height:100%!important;padding:12px!important;border-radius:18px;image-rendering:pixelated}
body[data-ci-mobile-login] #quickCodeMsg{font-size:15px!important;line-height:1.7;margin:0 0 14px!important}
body[data-ci-mobile-login] .Agreement{box-sizing:border-box;position:static!important;inset:auto!important;width:100%!important;height:auto!important;line-height:1.8!important;font-size:12px!important;white-space:normal!important;overflow-wrap:break-word;margin:20px 0 0!important;padding:0!important}
body[data-ci-mobile-login] .filingBox,body[data-ci-mobile-login] .lg-footer{box-sizing:border-box;position:static!important;inset:auto!important;transform:none!important;float:none!important;clear:both;width:100%!important;max-width:420px;height:auto!important;min-height:0!important;margin:20px auto 0!important;padding:0 8px 20px!important;font-size:11px!important;line-height:1.7;text-align:center;white-space:normal;overflow-wrap:anywhere;border:0!important;background:transparent!important}
body[data-ci-mobile-login] .filingBox>p{margin:0!important;padding:0!important;height:auto!important;line-height:inherit}
body[data-ci-mobile-login] .filingBox>p>span{box-sizing:border-box;display:block!important;position:static!important;float:none!important;width:auto!important;max-width:100%;height:auto!important;margin:0!important;padding:0!important;line-height:inherit;white-space:normal;overflow-wrap:anywhere}
body[data-ci-mobile-login] .filingBox .icpSpan{margin-top:6px!important}
#ci-login-tabs{display:flex;order:-2;width:100%;padding:4px;box-sizing:border-box;background:#f0f4fb;border-radius:14px;margin-bottom:14px;gap:4px}
#ci-login-tabs button{flex:1;min-width:0;min-height:46px;border:0;border-radius:11px;background:transparent;color:#738099;font:600 15px system-ui;cursor:pointer}
#ci-login-tabs button[aria-selected="true"]{background:white;color:#397dea;box-shadow:0 2px 8px #314f8520}
#ci-refresh-qr{display:block;min-height:44px;margin:0 auto;padding:0 24px;border:1px solid #dbe7fb;border-radius:12px;background:#f6f9ff;color:#397dea;font:500 14px system-ui;cursor:pointer}
`;
   document.head.appendChild(style);
  }
  document.body.setAttribute('data-ci-mobile-login','true');
  if(!document.body.hasAttribute('data-ci-login-mode'))document.body.setAttribute('data-ci-login-mode','qr');
  // Remove only the requested wording; keep official links and any consent controls.
  left.querySelectorAll('.Agreement').forEach(agreement=>{
   for(const node of agreement.childNodes){
    if(node.nodeType===Node.TEXT_NODE&&node.nodeValue.includes('我已阅读并同意学习通'))node.nodeValue=node.nodeValue.replace('我已阅读并同意学习通','');
   }
  });
  let tabs=document.querySelector('#ci-login-tabs');
  if(!tabs){
   tabs=document.createElement('div');tabs.id='ci-login-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','学习通登录方式');
   for(const [mode,label] of [['qr','扫码登录'],['account','账号登录']]){
    const button=document.createElement('button');button.type='button';button.textContent=label;button.setAttribute('role','tab');button.dataset.mode=mode;
    button.addEventListener('click',()=>{document.body.setAttribute('data-ci-login-mode',mode);updateTabs();});tabs.appendChild(button);
   }
   card.insertBefore(tabs,card.firstChild);
  }
  const refresh=right.querySelector('.ewmDisable a');
  if(refresh&&!document.querySelector('#ci-refresh-qr')){
   const button=document.createElement('button');button.id='ci-refresh-qr';button.type='button';button.textContent='刷新二维码';button.addEventListener('click',()=>{const official=right.querySelector('.ewmDisable a');if(official)official.click();});right.appendChild(button);
  }
  updateTabs();return true;
 }
 function updateTabs(){const mode=document.body.getAttribute('data-ci-login-mode');document.querySelectorAll('#ci-login-tabs button').forEach(button=>{const selected=button.dataset.mode===mode;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;});}
 root.CourseInboxMobileLoginUI={apply};
 apply();
 // The official page can insert the login card after WebView's page-finished callback.
 const observer=new MutationObserver(()=>apply());observer.observe(document.documentElement,{childList:true,subtree:true});
})(globalThis);
