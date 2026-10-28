'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
let now=100000,interval,captures=0;
const context={location:{href:'https://mooc1.chaoxing.com/mooc2/work/list'},document:{body:{}},MutationObserver:class{observe(){}},setInterval:f=>{interval=f},setTimeout,clearTimeout,Date:{now:()=>now},CourseInboxTasks:{extractDocument:()=>[{message_id:'same_task',captured_at:new Date(now).toISOString()}]},chrome:{runtime:{sendMessage:async m=>m.type==='sync-state'?{enabled:true}:(captures++,{accepted:m.messages.map(x=>x.message_id)})}}};
(async()=>{
 vm.runInNewContext(fs.readFileSync('browser-companion/task-content.js','utf8'),context);
 await new Promise(setImmediate);assert.equal(captures,1);
 now+=15000;await interval();assert.equal(captures,1,'avoid repeatedly rechecking within a minute');
 now+=45000;await interval();assert.equal(captures,2,'stable task source must periodically refresh observed platform state');
 console.log('PASS browser task replay refreshes platform checks once per minute');
})().catch(e=>{console.error(e);process.exitCode=1});
