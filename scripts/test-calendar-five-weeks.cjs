'use strict';
const assert=require('node:assert/strict');
const {chromium}=require('playwright');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:1000}});
    const errors=[];let writes=0;
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(['POST','PATCH','DELETE'].includes(r.method()))writes++});
    await page.goto((process.env.CI_TEST_URL||'http://127.0.0.1:8765')+'/#calendar');
    await page.locator('#calendarNow').waitFor();
    for(const today of ['2026-10-23','2026-11-01','2026-11-30','2027-01-01','2028-02-29']){
      await page.clock.setFixedTime(new Date(today+'T12:00:00+08:00'));
      await page.evaluate(()=>{month=new Date(cnLocalTime().slice(0,10)+'T12:00:00');renderCalendar()});
      const cells=page.locator('.calendar .day');
      assert.equal(await cells.count(),35,today+' must show five weeks');
      const index=await cells.evaluateAll(nodes=>nodes.findIndex(n=>n.classList.contains('today')));
      assert(index>=14&&index<21,today+' must be in third row, got '+index);
      const firstNumber=Number(await cells.first().locator('.day-number').textContent());
      const first=await page.evaluate(()=>{
        const d=new Date(month.getFullYear(),month.getMonth(),Number(cnLocalTime().slice(8,10)));
        d.setDate(d.getDate()-(d.getDay()+6)%7-14);return {day:d.getDay(),date:d.getDate()};
      });
      assert.equal(first.day,1);assert.equal(firstNumber,first.date);
      await page.locator('[data-month="1"]').click();
      assert.equal(await cells.count(),35);
      await page.locator('[data-month="-1"]').click();
      assert.equal(await cells.count(),35);
      await page.locator('[data-month="0"]').click();
      assert.equal(await page.locator('.calendar .day.today').count(),1);
      const returnedIndex=await cells.evaluateAll(nodes=>nodes.findIndex(n=>n.classList.contains('today')));
      assert(returnedIndex>=14&&returnedIndex<21,'return to current month keeps today centered');
    }
    await page.evaluate(()=>{
      const due=cnLocalTime().slice(0,10);
      state.tasks=[{id:'visible',title:'显示任务',course:'测试',status:'submitted',deadline:due},
                   {id:'hidden',title:'取消任务',course:'测试',status:'cancelled',deadline:due}];
      renderCalendar();
    });
    assert.equal(await page.locator('.calendar-task.submitted').count(),1);
    assert.equal(await page.locator('.calendar-task').count(),1);
    await page.setViewportSize({width:390,height:900});
    assert.equal(await page.locator('.calendar .day').count(),35);
    assert.deepEqual(errors,[]);assert.equal(writes,0);
    await page.screenshot({path:'artifacts/calendar-five-weeks.png',fullPage:true});
    console.log('PASS: fixed five weeks, today centered across month/year/leap boundaries, navigation, task states and mobile rendering; no business writes.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
