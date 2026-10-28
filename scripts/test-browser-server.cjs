'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {test}=require('node:test');
const {createTestServer}=require('./lib/browser-test-server.cjs');

test('isolated server supports authenticated GET, POST and PATCH and repeated cleanup',async()=>{
 const fixture=createTestServer('campusinbox-helper-');
 try{
  const {api,token,url}=await fixture.start();
  assert.equal(new URL(url).hostname,'127.0.0.1');
  assert(token.length>=24);
  assert.deepEqual(await api('tasks'),[]);
  const intake=await api('messages',{text:'《测试课程》实验一，请提交实验报告。',captured_at:'2026-10-24T09:00:00+08:00'});
  const task=await api('proposals/'+intake.proposals[0].id+'/confirm',{});
  assert.equal((await api('tasks/'+task.id,{status:'done',expected_version:task.version},'PATCH')).status,'done');
  await assert.rejects(api('tasks/not-found'),/消息不存在|任务不存在|404/);
  const scoped=(await api('chaoxing/pairing')).token;
  await api('chaoxing/messages',{kind:'course_notice',message_id:'helper-notice',title:'测试通知',text:'明天上课。',course:'测试课程',conversation:'一班',captured_at:'2026-10-24T09:00:00+08:00',url:'https://notice.chaoxing.com/pc/notice/helper/detail',attachments:[]},'POST',scoped);
 }finally{await fixture.close()}
 assert.equal(fs.existsSync(fixture.directory),false);
 await fixture.close();
});

test('missing interpreter rejects and cleans up',async()=>{
 const fixture=createTestServer('campusinbox-helper-missing-',{python:path.join(__dirname,'missing-python.exe')});
 try{await assert.rejects(fixture.start(),/ENOENT/)}finally{await fixture.close()}
 assert.equal(fs.existsSync(fixture.directory),false);
});

test('early process exit rejects with stderr instead of waiting for timeout',async()=>{
 const fixture=createTestServer('campusinbox-helper-exit-',{python:process.execPath});
 try{await assert.rejects(fixture.start(),/server exited.*bad option: -B/s)}finally{await fixture.close()}
 assert.equal(fs.existsSync(fixture.directory),false);
});

test('startup timeout can be cleaned up without leaving a child or temporary database',async()=>{
 const fixture=createTestServer('campusinbox-helper-timeout-',{timeout:1});
 try{await assert.rejects(fixture.start(),/startup timeout/)}finally{await fixture.close()}
 assert.equal(fs.existsSync(fixture.directory),false);
});
