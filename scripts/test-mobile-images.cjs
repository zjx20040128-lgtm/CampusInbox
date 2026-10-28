'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright');
const file=path.join(__dirname,'../android/app/src/main/assets/mobile-images.js');
const adapter=fs.existsSync(file)?fs.readFileSync(file,'utf8'):'';
const cover='http://p.ananas.chaoxing.com/fixture/cover.png?size=240#cover';
const secureCover='https://p.ananas.chaoxing.com/fixture/cover.png?size=240#cover';
const pixel=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=','base64');
const fixture=`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="img-src https: data: blob:"><style>img{width:180px;height:100px}</style></head><body><a id="course" href="#course" onclick="event.preventDefault();courseClicks++"><img id="cover" src="${cover}" alt="原课程封面"></a><p id="evidence">原始通知：请阅读第三章。</p><form onsubmit="event.preventDefault();submits++"><input id="account" value="尚未提交的内容"><button>提交</button></form><script>window.courseClicks=0;window.submits=0;window.originalCover=document.querySelector('#cover');window.originalInput=document.querySelector('#account');window.imageErrors=0;originalCover.addEventListener('error',()=>imageErrors++);</script></body></html>`;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.route('**/*',route=>route.request().resourceType()==='image'
   ?route.fulfill({status:200,contentType:'image/png',body:pixel})
   :route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fixture}));
  async function load(url){await page.goto(url);if(adapter)await page.evaluate(adapter);}
  for(const width of [320,390,480]){
   await page.setViewportSize({width,height:740});
   await load('https://mooc2-ans.chaoxing.com/visit/interaction');
   assert.equal(await page.locator('#cover').getAttribute('src'),secureCover,'known HTTP course cover must explicitly use HTTPS, not depend on browser auto-upgrade');
   await page.waitForFunction(()=>originalCover.complete&&originalCover.naturalWidth>0);
   assert(await page.evaluate(()=>originalCover===document.querySelector('#cover')&&originalInput===document.querySelector('#account')),'preserve original image and form nodes');
   assert.equal(await page.locator('#cover').getAttribute('alt'),'原课程封面');
   assert.equal(await page.locator('#evidence').textContent(),'原始通知：请阅读第三章。');
   assert.equal(await page.locator('#account').inputValue(),'尚未提交的内容');
   assert.equal(await page.evaluate(()=>submits),0,'image repair must not submit a form');
   await page.locator('#course').click();assert.equal(await page.evaluate(()=>courseClicks),1,'original course link handler survives');
   const box=await page.locator('#cover').boundingBox();assert(box&&box.width>0&&box.x+box.width<=width,'image remains visible on phone-width page');
  }
  await page.evaluate(()=>{const img=document.createElement('img');img.id='dynamic';img.src='http://p.ananas.chaoxing.com/fixture/next.png?token=fixture#part';document.body.append(img);});
  await page.waitForFunction(()=>document.querySelector('#dynamic').getAttribute('src')==='https://p.ananas.chaoxing.com/fixture/next.png?token=fixture#part');
  await page.waitForFunction(()=>document.querySelector('#dynamic').complete&&document.querySelector('#dynamic').naturalWidth>0);
  await page.locator('#dynamic').evaluate(img=>img.setAttribute('src','http://p.ananas.chaoxing.com:80/fixture/replaced.png?size=400'));
  await page.waitForFunction(()=>document.querySelector('#dynamic').getAttribute('src')==='https://p.ananas.chaoxing.com/fixture/replaced.png?size=400');
  await page.locator('#dynamic').evaluate(img=>img.src='http://p.ananas.chaoxing.com/fixture/contact@course.png?contact=teacher@example.org#mail');
  await page.waitForFunction(()=>document.querySelector('#dynamic').getAttribute('src')==='https://p.ananas.chaoxing.com/fixture/contact@course.png?contact=teacher@example.org#mail');
  await page.evaluate(()=>{const video=document.createElement('video');video.id='non-image';document.body.append(video);});
  await page.locator('#non-image').evaluate(video=>video.setAttribute('src','http://p.ananas.chaoxing.com/fixture/video.mp4'));
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('#non-image').getAttribute('src'),'http://p.ananas.chaoxing.com/fixture/video.mp4','image compatibility must not rewrite unrelated src attributes');
  for(const src of [
   'https://p.ananas.chaoxing.com/fixture/already.png',
   '//p.ananas.chaoxing.com/fixture/protocol-relative.png',
   'http://outside.chaoxing.invalid/unverified.png','http://outside.example/cover.png',
   'http://p.ananas.chaoxing.com.evil.example/cover.png',
   'http://p.ananas.chaoxing.com:8080/cover.png',
   'http://user:password@p.ananas.chaoxing.com/cover.png',
   'http://@p.ananas.chaoxing.com/cover.png','http://:@p.ananas.chaoxing.com/cover.png',
   'h\tttp://@p.ananas.chaoxing.com/cover.png','http:\\\\@p.ananas.chaoxing.com/cover.png',
   '\u0001http://@p.ananas.chaoxing.com/cover.png',
   'data:image/png;base64,'+pixel.toString('base64'),'blob:https://mooc2-ans.chaoxing.com/fixture',
   '/same-origin.png','not a remote URL'
  ]){
   await page.evaluate(src=>{const img=document.createElement('img');img.id='untouched';img.setAttribute('src',src);document.body.append(img);},src);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   assert.equal(await page.locator('#untouched').getAttribute('src'),src,'only verified host and default HTTP port may be upgraded: '+src);
   await page.locator('#untouched').evaluate(img=>img.remove());
  }
  await page.evaluate(()=>{window.writes=0;new MutationObserver(records=>writes+=records.filter(r=>r.type==='attributes').length).observe(document.body,{subtree:true,attributes:true,attributeFilter:['src']});});
  for(let i=0;i<3;i++)await page.evaluate(adapter);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.evaluate(()=>writes),0,'repeat injection must not churn already-upgraded attributes');
  await page.route('https://p.ananas.chaoxing.com/fixture/broken.png',route=>route.fulfill({status:404,body:''}));
  await page.evaluate(()=>{const img=document.createElement('img');img.id='broken';img.src='http://p.ananas.chaoxing.com/fixture/broken.png';window.originalErrors=0;img.addEventListener('error',()=>originalErrors++);document.body.append(img);});
  await page.waitForFunction(()=>document.querySelector('#broken').getAttribute('src')==='https://p.ananas.chaoxing.com/fixture/broken.png'&&document.querySelector('#broken').complete&&originalErrors>0);
  assert.equal(await page.locator('#broken').getAttribute('src'),'https://p.ananas.chaoxing.com/fixture/broken.png','HTTPS failure must not fall back to HTTP');
  assert.equal(await page.locator('#broken').evaluate(img=>img.naturalWidth),0,'leave unavailable image visibly unavailable instead of fabricating success');
  for(const url of ['https://i.chaoxing.com/','https://passport2.chaoxing.com/login','https://notice.chaoxing.com/pc/notice/fixture/detail']){
   await load(url);assert.equal(await page.locator('#cover').getAttribute('src'),secureCover,'repair images independently of page-layout recognition or original layout');
  }
  await load('https://i.chaoxing.com/');
  await page.evaluate(()=>{const frame=document.createElement('iframe');frame.id='cross-origin';frame.src='https://mooc2-ans.chaoxing.com/fixture-embed';document.body.append(frame);});
  await page.frameLocator('#cross-origin').locator('#cover').waitFor();
  await page.evaluate(adapter);
  assert.equal(await page.locator('#cover').getAttribute('src'),secureCover,'top-level image is repaired');
  assert.equal(await page.frameLocator('#cross-origin').locator('#cover').getAttribute('src'),cover,'cross-origin child document is outside top-level injection; open course page separately');
  for(const url of ['http://i.chaoxing.com/','https://unrelated.example/','https://i.chaoxing.com.evil.example/','https://i.chaoxing.com:8443/']){
   await load(url);assert.equal(await page.locator('#cover').getAttribute('src'),cover,'nonofficial or insecure page must stay untouched: '+url);
  }
  console.log('PASS: verified HTTP covers load over HTTPS at 320/390/480px; dynamic images and refresh; strict URL boundaries; original nodes/forms/evidence retained; no mutation loop');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
