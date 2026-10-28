const $=selector=>document.querySelector(selector);
async function status() {
  const state=await chrome.storage.local.get(['queue','delivered','lastSuccess','lastError','sourceError','enabled','rejected','incomplete']);
  $('#pending').textContent=state.queue?.length||0;
  $('#rejected').textContent=state.rejected?.length||0;
  $('#incomplete').textContent=state.incomplete?.length||0;
  $('#delivered').textContent=state.delivered||0;
  $('#lastSuccess').textContent=state.lastSuccess?new Date(state.lastSuccess).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚无';
  $('#lastError').textContent=state.lastError||state.sourceError||(state.enabled?'已启用；请保持学习通收件箱或聊天会话打开。':'未启用');
}
chrome.storage.local.get(['token','enabled','readInstructions']).then(state=>{$('#token').value=state.token||'';$('#enabled').checked=Boolean(state.enabled);$('#readInstructions').checked=state.readInstructions!==false;return status()});
$('#config').addEventListener('submit',async event=>{
  event.preventDefault();
  const token=$('#token').value.trim();
  if (!/^[a-f0-9]{64}$/.test(token)) {$('#notice').textContent='请复制 CourseInbox 的网页同步专用令牌。';return}
  await chrome.storage.local.set({token,enabled:$('#enabled').checked,readInstructions:$('#readInstructions').checked,lastError:'',sourceError:''});
  $('#notice').textContent='配置已保存。启用后请刷新学习通收件箱或消息网页，或等待下一次自动扫描。';
  await chrome.runtime.sendMessage({type:'retry'});await status();
});
$('#retry').addEventListener('click',async()=>{await chrome.runtime.sendMessage({type:'retry'});await status()});
chrome.storage.onChanged.addListener(status);
