/* Read-only browser regression for the simplified task filter menu. */
'use strict';
const assert=require('node:assert/strict');
const {chromium}=require('playwright');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage();
    await page.goto('http://127.0.0.1:8765/#tasks');
    await page.locator('#statusFilter').waitFor();
    await page.evaluate(()=>{
      const today=cnLocalTime().slice(0,10);
      const past=cnLocalTime(new Date(Date.now()-2*86400000)).slice(0,10);
      const future=cnLocalTime(new Date(Date.now()+2*86400000)).slice(0,10);
      const task=(id,status,deadline)=>({id,title:id,course:'筛选测试',scope:'示例班级',kind:'assignment',status,deadline});
      state.tasks=[task('逾期待开始','pending',past),task('未来待开始','pending',future),task('今天待开始','pending',today),task('未定截止待开始','pending',null),task('进行中已逾期','in_progress',past),task('已完成已逾期','done',past),task('已提交','submitted',past),task('已取消','cancelled',past)];
      filters.search='';filters.course='';filters.status='active';renderTasks();
    });
    const options=await page.locator('#statusFilter option').allTextContents();
    assert.deepEqual(options,['尚未提交','全部任务','已逾期','已做完','已提交']);
    const titles=()=>page.locator('.task-row h3').allTextContents();
    assert.deepEqual(await titles(),['未来待开始','今天待开始','未定截止待开始']);
    await page.locator('#statusFilter').selectOption('overdue');
    assert.deepEqual(await titles(),['逾期待开始','进行中已逾期','已完成已逾期']);
    await page.locator('#statusFilter').selectOption('submitted');
    assert.deepEqual(await titles(),['已提交']);
    await page.locator('#statusFilter').selectOption('all');
    assert.equal((await titles()).length,8);
    await page.evaluate(()=>{refresh(false,state);renderToday()});
    assert.equal((await page.locator('#taskBadge').textContent()).trim(),'3');
    assert.match((await page.locator('.stat-number').first().textContent()).trim(),/^3\s*项任务$/);
    await page.reload();
    await page.locator('#statusFilter').waitFor();
    const live=await page.evaluate(()=>({
      active:state.tasks.filter(t=>!['submitted','cancelled'].includes(t.status)&&!isCalendarTaskOverdue(t)).length,
      overdue:state.tasks.filter(t=>isCalendarTaskOverdue(t)).length,
    }));
    assert.equal((await titles()).length,live.active);
    await page.locator('#statusFilter').selectOption('overdue');
    assert.equal((await titles()).length,live.overdue);
    console.log('PASS: task filters show only useful choices and preserve active and overdue results');
    console.log(JSON.stringify({liveActive:live.active,liveOverdue:live.overdue}));
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
