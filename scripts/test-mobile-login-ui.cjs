'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const asset=path.join(root,'android/app/src/main/assets/mobile-login-ui.js');
const adapter=fs.existsSync(asset)?fs.readFileSync(asset,'utf8'):'';
// Reproduces the current official 900px card and original login/refresh handlers.
const fixture=`<!doctype html><html><head><style>
body{margin:0;font:12px sans-serif;background:#f4f5fa}.lg-container{width:100%;height:100vh;position:relative}
.main{width:900px;height:546px;position:absolute;top:35%;left:50%;margin-left:-450px;background:white}.default-login{width:900px;height:546px;position:relative}
#leftdiv{box-sizing:border-box;width:540px;height:546px;padding:68px 90px 51px}#rightdiv{box-sizing:border-box;position:absolute;right:0;top:0;width:360px;height:546px;padding:155px 64px 0}
.lg-item{position:relative;width:360px;height:48px;margin-bottom:24px}.lg-item input{box-sizing:border-box;width:360px;height:48px;padding-left:54px}
#loginBtn{width:360px;height:48px;margin-top:40px;background:linear-gradient(90deg,#55a8ff,#6561ff);color:white;border:0}.ecode-box{width:179px;height:184px;padding:25px;position:relative}
#quickCode{width:129px;height:134px}.ewmDisable{position:absolute;inset:0;display:none;background:#ffffffee}.Agreement{top:25px;position:relative}.fs14{font-size:14px}
.filingBox{position:absolute;bottom:0;width:100%;height:60px;text-align:center;border-top:1px solid #ddd}.filingBox p{margin:0}.filingBox span{display:inline-block;padding:0 15px;line-height:18px}.lg-top .service{position:absolute;right:30px;top:30px}
</style></head><body><div class="lg-container"><div class="main default-login-main heightCalc"><div class="default-login">
<div class="lg-top"><a id="kf" class="service" href="/v5/toCustomer" onclick="event.preventDefault();customerOpens++">客服</a></div><div id="leftdiv" class="left"><h3 class="lg-title">用户登录</h3><form id="official-form"><input type="hidden" name="fid" value="fixture-config"><div class="lg-item"><input id="phone" placeholder="手机号/超星号"></div><div class="lg-item"><input id="pwd" type="password" placeholder="学习通密码"></div><div class="btns-box"><button id="loginBtn" type="button">登录</button></div></form><div class="clearaft fs14">验证码登录 · 其他登录方式</div><p class="Agreement" style="bottom:-25px"><input type="checkbox" id="agreement">我已阅读并同意学习通 <a href="https://homewh.chaoxing.com/agree/privacyPolicy?appId=900001" onclick="event.preventDefault();policyOpens++">《隐私政策》</a> 和 <a href="https://homewh.chaoxing.com/agree/userAgreement?appId=900001">《用户协议》</a></p></div>
<div id="rightdiv" class="right"><div id="step1"><div class="ecode-box"><div class="ewmDisable"><p>二维码已失效</p><a href="javascript:void(0)" onclick="refreshes++">重新获取</a></div><img id="quickCode" alt="官方二维码" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Crect width='240' height='240' fill='white'/%3E%3Cpath d='M20 20h60v60H20zM160 20h60v60h-60zM20 160h60v60H20zM100 100h20v20h-20zM140 140h40v40h-40z' fill='black'/%3E%3C/svg%3E"></div><p id="quickCodeMsg" class="tip">使用学习通APP扫码登录</p></div><div id="step2" style="display:none">请在学习通上点击确认以登录</div></div>
</div></div><div class="filingBox"><p><span>Copyright © <t>2026</t> 北京世纪超星信息技术发展有限责任公司 <a href="https://beian.miit.gov.cn">京ICP备10040544号-2</a></span><span class="icpSpan"><i></i><a href="http://www.beian.gov.cn/">京公网安备 11010802021885号</a></span></p></div></div><div id="official-verification" style="display:none;position:fixed;inset:20px;background:white;z-index:999">官方额外验证</div>
<script>window.logins=0;window.refreshes=0;window.customerOpens=0;window.policyOpens=0;window.originalForm=document.querySelector('form');window.originalPhone=document.querySelector('#phone');window.originalPolicyLinks=Array.from(document.querySelectorAll('.Agreement a'));window.originalAgreement=document.querySelector('#agreement');loginBtn.onclick=()=>logins++;</script></body></html>`;
async function checkPolicyPresentation(page){
 assert.equal((await page.locator('.Agreement').innerText()).includes('我已阅读并同意学习通'),false,'remove only the requested introductory sentence from the displayed policy row');
 const links=page.locator('.Agreement a');assert.equal(await links.count(),2,'both official policy links remain accessible');
 assert(await page.evaluate(()=>originalPolicyLinks.every((link,index)=>link===document.querySelectorAll('.Agreement a')[index])&&originalAgreement===document.querySelector('#agreement')),'preserve original policy and consent nodes');
 assert.equal(await links.first().getAttribute('href'),'https://homewh.chaoxing.com/agree/privacyPolicy?appId=900001');
 assert.equal(await links.last().getAttribute('href'),'https://homewh.chaoxing.com/agree/userAgreement?appId=900001');
 assert(await links.first().isVisible()&&await links.last().isVisible(),'do not hide the official policies');
}
async function checkFooterLayout(page,label){
 const agreement=await page.locator('.Agreement').boundingBox(),footer=await page.locator('.filingBox').boundingBox(),card=await page.locator('.default-login-main').boundingBox();
 assert(footer.y>=agreement.y+agreement.height+8,`${label}: copyright and registration must stay below the complete policy text`);
 assert(footer.y>=card.y+card.height,`${label}: footer must not overlay the login card`);
 const tabs=await page.locator('#ci-login-tabs').boundingBox(),customer=await page.locator('#kf').boundingBox();
 assert(customer.y>=tabs.y+tabs.height,`${label}: customer service needs its own row outside the login tabs`);
 const copyright=await page.locator('.filingBox span').first().boundingBox(),registration=await page.locator('.icpSpan').boundingBox();
 assert(registration.y>=copyright.y+copyright.height,`${label}: registration must flow below copyright text`);
}
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.route('https://**/*',route=>route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fixture}));
  for(const width of [320,390,480]){
   await page.setViewportSize({width,height:740});await page.goto('https://passport2.chaoxing.com/login');
   if(adapter)await page.evaluate(adapter);
   const card=await page.locator('.main').boundingBox();
   assert(card.x>=0&&card.x+card.width<=width+1,`${width}px: login card must fit the phone width instead of shrinking a 900px desktop card`);
   assert(card.y<100,'login card must start near the top, without desktop vertical centering');
   const qr=await page.locator('#quickCode').boundingBox();assert(qr.width>=220&&qr.width<=280,'QR must be large enough to scan');
   assert.equal(await page.locator('#official-form').isVisible(),false,'QR tab must not squeeze the account form beside it');
   assert(await page.locator('.Agreement').isVisible(),'official policy and agreement must remain accessible in QR mode');
   await checkPolicyPresentation(page);
   await page.locator('.Agreement a').first().click();assert.equal(await page.evaluate(()=>policyOpens),1,'original policy-link handler is preserved');
   await checkFooterLayout(page,`${width}px QR`);
   await page.locator('#kf').click();assert.equal(await page.evaluate(()=>customerOpens),1,'original customer-service handler is preserved');
   await page.getByRole('tab',{name:'账号登录'}).click();
   assert(await page.locator('#leftdiv').isVisible());assert.equal(await page.locator('#rightdiv').isVisible(),false);
   await checkPolicyPresentation(page);
   const phone=await page.locator('#phone').boundingBox(),login=await page.locator('#loginBtn').boundingBox();
   assert(phone.width>=width-100&&phone.height>=48,'account input must be usable at phone size');assert(login.height>=48&&login.width>=phone.width-1);
   await checkFooterLayout(page,`${width}px account`);
   await page.setViewportSize({width,height:420});await checkFooterLayout(page,`${width}px keyboard-height`);await page.setViewportSize({width,height:740});
   await page.locator('#phone').fill('fixture-account');await page.locator('#pwd').fill('fixture-only-password');
   await page.locator('#loginBtn').click();assert.equal(await page.evaluate(()=>logins),1,'original official login handler remains attached');
   await page.getByRole('tab',{name:'扫码登录'}).click();await page.getByRole('tab',{name:'账号登录'}).click();
   assert.equal(await page.locator('#phone').inputValue(),'fixture-account','switching modes must not reset the official form');
   assert(await page.evaluate(()=>originalForm===document.querySelector('form')&&originalPhone===document.querySelector('#phone')),'do not clone or replace official controls');
   assert.equal(await page.locator('#agreement').isChecked(),false,'adaptation must not accept an official agreement for the user');
   await page.locator('#agreement').check();assert(await page.locator('#agreement').isChecked(),'the user can still operate an official consent control when present');await page.locator('#agreement').uncheck();
   await page.evaluate(adapter);assert.equal(await page.getByRole('tab').count(),2,'repeated page callbacks must not duplicate tabs');
   await checkPolicyPresentation(page);
   await page.getByRole('tab',{name:'扫码登录'}).click();await page.getByRole('button',{name:'刷新二维码'}).click();assert.equal(await page.evaluate(()=>refreshes),1,'refresh delegates to the original official QR handler');
   await page.screenshot({path:path.join(root,`artifacts/mobile-login-qr-${width}.png`),fullPage:true});
   await page.locator('.ewmDisable').evaluate(el=>el.style.display='block');assert(await page.getByText('二维码已失效').isVisible(),'official expired state remains visible');
   await page.locator('#official-verification').evaluate(el=>el.style.display='block');assert(await page.getByText('官方额外验证',{exact:true}).isVisible(),'official verification must not be hidden');
   await page.locator('#official-verification').evaluate(el=>el.style.display='none');
   const noOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);assert(noOverflow,'page must not overflow horizontally');
   await page.getByRole('tab',{name:'账号登录'}).click();await page.screenshot({path:path.join(root,`artifacts/mobile-login-account-${width}.png`),fullPage:true});
  }
  await page.goto('https://unrelated.example/login');await page.evaluate(adapter);assert.equal(await page.getByRole('tab').count(),0,'non-official pages must be untouched');
  await page.goto('https://passport2.chaoxing.com/login-other');await page.evaluate(adapter);assert.equal(await page.getByRole('tab').count(),0,'unknown official authentication variants remain untouched');
  await page.goto('https://passport2.chaoxing.com/login');await page.locator('#rightdiv').evaluate(el=>el.remove());await page.evaluate(adapter);assert.equal(await page.getByRole('tab').count(),0,'unknown official layouts stay original');
  console.log('PASS: phone login layout at 320/390/480px; original form/QR/verification preserved; no overflow or unauthorized adaptation');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
