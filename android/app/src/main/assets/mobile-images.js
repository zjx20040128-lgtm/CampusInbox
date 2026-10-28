/* Upgrade image requests on official Chaoxing pages to HTTPS.
 * Never relax mixed-content or certificate checks, and never downgrade failures. */
(function(){
 'use strict';
 const page=new URL(location.href);
 if(page.protocol!=='https:'||page.username||page.password||page.port&&page.port!=='443'
   ||!(page.hostname==='chaoxing.com'||page.hostname.endsWith('.chaoxing.com')))return;
 if(globalThis.CourseInboxMobileImages){globalThis.CourseInboxMobileImages.apply();return;}
 function upgradeURL(source){
  if(!source)return source;
  // URL serialization drops empty userinfo; leave that syntax untouched too.
  if(/^[\u0000-\u0020]*http:[\\/]*[^\\/?#]*@/i.test(source.replace(/[\t\r\n]/g,'')))return source;
  try{
   const url=new URL(source,location.href);
   if(url.protocol!=='http:'||!(url.hostname==='chaoxing.com'||url.hostname.endsWith('.chaoxing.com'))
     ||url.username||url.password||url.port&&url.port!=='80')return source;
   url.protocol='https:';
   if(url.port==='80')url.port='';
   return url.href;
  }catch(ignored){return source;}
 }
 function upgradeSrcset(value){
  let result='',cursor=0;
  while(cursor<value.length){
   const leading=cursor;
   while(cursor<value.length&&(/[\t\n\f\r ]/.test(value[cursor])||value[cursor]===','))cursor++;
   result+=value.slice(leading,cursor);
   if(cursor>=value.length)break;
   const start=cursor;
   while(cursor<value.length&&!/[\t\n\f\r ]/.test(value[cursor]))cursor++;
   let candidate=value.slice(start,cursor),separators='';
   while(candidate.endsWith(',')){candidate=candidate.slice(0,-1);separators=','+separators;}
   result+=candidate?upgradeURL(candidate):candidate;
   result+=separators;
   if(separators)continue;
   const descriptorStart=cursor;let parentheses=0;
   while(cursor<value.length){
    const char=value[cursor];
    if(char==='(')parentheses++;
    else if(char===')'&&parentheses)parentheses--;
    else if(char===','&&!parentheses)break;
    cursor++;
   }
   result+=value.slice(descriptorStart,cursor);
   if(cursor<value.length)result+=value[cursor++];
  }
  return result;
 }
 function upgradeCSS(value){
  return value.replace(/url\(\s*(["']?)(.*?)\1\s*\)/gi,(match,quote,source)=>{
   const trimmed=source.trim(),next=upgradeURL(trimmed);
   return next===trimmed?match:`url(${quote}${next}${quote})`;
  });
 }
 function upgradeStyle(element){
  const style=element.getAttribute('style');
  if(style){const next=upgradeCSS(style);if(next!==style)element.setAttribute('style',next);}
  if(element.tagName==='STYLE'){
   const css=element.textContent,next=upgradeCSS(css);
   if(next!==css)element.textContent=next;
  }
 }
 function upgrade(element){
  upgradeStyle(element);
  if(element.tagName==='IMG'){
   const source=element.getAttribute('src');
   if(source){const next=upgradeURL(source);if(next!==source)element.setAttribute('src',next);}
  }
  if(element.tagName==='IMG'||element.tagName==='SOURCE'){
   const srcset=element.getAttribute('srcset');
   if(srcset){const next=upgradeSrcset(srcset);if(next!==srcset)element.setAttribute('srcset',next);}
  }
 }
 function apply(root=document){
  if(root.nodeType===1&&(root.tagName==='IMG'||root.tagName==='SOURCE'||root.tagName==='STYLE'||root.hasAttribute('style')))upgrade(root);
  if(root.querySelectorAll)root.querySelectorAll('img[src],img[srcset],source[srcset],[style],style').forEach(upgrade);
 }
 globalThis.CourseInboxMobileImages={apply};
 apply();
 new MutationObserver(records=>{
  for(const record of records){
   if(record.type==='attributes')upgrade(record.target);
   else if(record.target.nodeType===1&&record.target.tagName==='STYLE')upgrade(record.target);
   else record.addedNodes.forEach(apply);
  }
 }).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['src','srcset','style']});
})();
