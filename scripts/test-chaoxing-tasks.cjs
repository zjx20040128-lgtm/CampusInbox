/* Real browser + sanitized task-center DOM fixtures; no account data. */
'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {chromium}=require('playwright');
let browser;
(async()=>{
 browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage();
 await page.setContent(`
  <main data-course="数据库系统" data-class="计科1班">
   <article class="work-list-item" data-task-id="work-42" data-task-kind="experiment">
    <a class="task-title" href="https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=1&workId=42">数据库实验三</a>
    <span class="teacher">王老师</span><span class="deadline">截止：2026-10-13 23:59</span>
    <span class="publish-time">发布时间：2026-10-10 08:30</span>
    <span class="submission-method">学习通上传</span><span class="status">未提交</span>
    <p class="task-description">完成实验并上传报告。</p>
   </article>
   <article class="exam-list-item" data-task-id="exam-7" data-task-kind="exam">
    <a class="task-title" href="https://mooc1.chaoxing.com/exam-ans/exam/test?courseId=1&id=7">期中考试</a>
    <span class="deadline">开始：2026-10-20 09:00，截止：2026-10-20 11:00</span><span class="status">未开始</span>
   </article>
  </main>`);
 await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../browser-companion/tasks.js'),'utf8')});
 const jobs=await page.evaluate(()=>CourseInboxTasks.extractDocument(document,location.href));
 assert.equal(jobs.length,2);
 assert.deepEqual(jobs.map(x=>[x.title,x.task_type]),[['数据库实验三','experiment'],['期中考试','exam']]);
 assert.match(jobs[0].message_id,/^task_work-42_[a-z0-9]{7}_[a-z0-9]{7}$/);assert.match(jobs[1].message_id,/^task_exam-7_[a-z0-9]{7}_[a-z0-9]{7}$/);
 assert.equal(jobs[0].course,'数据库系统');assert.equal(jobs[0].conversation,'计科1班');
 assert.equal(jobs[0].deadline,'2026-10-13T23:59:00+08:00');assert.equal(jobs[0].submission_method,'学习通上传');
 assert.equal(jobs[0].published_at,'2026-10-10T08:30:00+08:00');
 assert.equal(jobs[1].published_at,null,'exam start time must not become publication');
 await page.locator('.publish-time').evaluate(node=>node.setAttribute('data-published-at','2026-10-10T00:30:00Z'));
 const zoned=await page.evaluate(()=>CourseInboxTasks.extractDocument(document,location.href));
 assert.equal(Date.parse(zoned[0].published_at),Date.parse('2026-10-10T00:30:00Z'),'explicit publication time zones must be retained');
 await page.locator('.publish-time').evaluate(node=>node.removeAttribute('data-published-at'));
 assert.equal(jobs[1].deadline,'2026-10-20T11:00:00+08:00');
 const other=await page.evaluate(()=>CourseInboxTasks.extractDocument(new DOMParser().parseFromString('<main data-course="操作系统"><article data-task-id="work-42"><a class="task-title" href="https://mooc1.chaoxing.com/mooc-ans/work/view?courseId=2&workId=42">实验三</a><span class="deadline">截止：2026-10-14 23:59</span></article></main>','text/html'),location.href));
 assert.notEqual(other[0].message_id,jobs[0].message_id,'the same platform row id in different courses must not collide');
 const changed=await page.evaluate(()=>{document.querySelector('.work-list-item .deadline').textContent='截止：2026-10-15 23:59';return CourseInboxTasks.extractDocument(document,location.href)});
 assert.notEqual(changed[0].message_id,jobs[0].message_id,'a deadline extension must create new source evidence');
 assert.equal(changed[0].deadline,'2026-10-15T23:59:00+08:00');
 await page.setContent('<ul class="bottomList"><li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&workId=43"><div class="right-content"><p class="overHidden2">真实列表作业</p><p class="status">待批阅</p></div></li></ul>');
 const realShape=await page.evaluate(()=>CourseInboxTasks.extractDocument(document,location.href,{course:'示例课程',taskType:'assignment'}));
 assert.equal(realShape.length,1);assert.equal(realShape[0].course,'示例课程');assert.equal(realShape[0].deadline,null);
 await page.locator('.bottomList li').evaluate(node=>node.insertAdjacentHTML('beforeend','<span class="time">剩余319小时22分钟</span>'));
 const countdown=await page.evaluate(()=>CourseInboxTasks.extractDocument(document,location.href,{course:'示例课程',taskType:'assignment'}));
 await page.locator('.time').evaluate(node=>node.textContent='剩余319小时20分钟');
 const tick=await page.evaluate(()=>CourseInboxTasks.extractDocument(document,location.href,{course:'示例课程',taskType:'assignment'}));
 assert.equal(tick[0].message_id,countdown[0].message_id,'countdown ticks are observations, not a new task revision');
 assert.match(tick[0].text,/剩余319小时20分钟/,'retain the original observed body as source evidence');
 console.log('PASS: structured Chaoxing assignment and exam center DOM extraction');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>browser?.close());
