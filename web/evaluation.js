'use strict';
window.CourseInboxEvaluation=(()=>{
  let root=null,ctx=null,timer=null,generation=0,labelRequest=0,reportRequest=0;
  const s={datasets:[],dataset:'',tab:'results',page:null,item:null,draft:[],dirty:false,revision:'',reports:[],report:null,reportId:'',models:{available:false,models:[]},chosen:new Set(),job:{state:'idle'},caseRun:0};
  const q=(selector)=>root?.querySelector(selector);
  const h=value=>ctx.esc(value);
  const active=()=>root?.isConnected&&ctx.isActive();
  const running=()=>['queued','running','cancelling'].includes(s.job.state);
  const request=(path,options)=>ctx.json('/api/evaluation/'+path,options);
  const post=(path,body)=>request(path,{method:'POST',body});
  const pct=value=>typeof value==='number'&&Number.isFinite(value)?(value*100).toFixed(1).replace(/\.0$/,'')+'%':'未覆盖';
  const seconds=value=>typeof value==='number'&&Number.isFinite(value)?(value/1000).toFixed(value<1000?3:1)+' 秒':'未测量';
  const date=value=>value?String(value).slice(0,19).replace('T',' '):'时间未记录';
  const name=run=>run.mode==='rules'?'本地规则':'规则 + '+(run.model||'本机模型');
  function error(message=''){if(q('#evaluationError'))q('#evaluationError').textContent=message}
  function config(){
    if(!active())return;
    const dataset=s.datasets.find(d=>d.id===s.dataset);
    q('#evaluationDataset').innerHTML=s.datasets.length?s.datasets.map(d=>`<option value="${h(d.id)}" ${d.id===s.dataset?'selected':''}>${d.schema===1?'已有核对样本':d.partitioned?'独立评测集':'收件箱通知'+(s.datasets.filter(x=>x.schema===2).length>1?' '+(s.datasets.filter(x=>x.schema===2).indexOf(d)+1):'')}</option>`).join(''):'<option value="">尚无标注数据集</option>';
    q('#evaluationDatasetSummary').textContent=dataset?`已核对 ${dataset.reviewed} 条 · 待核对 ${dataset.unreviewed} 条${dataset.reviewed?'':'，先到“核对通知”填写答案。'}${dataset.partitioned?' · 仅评测所选分组，开发集用于调参。':''}`:'在“更多选项”中从收件箱选取通知。';
    q('#evaluationHoldout').disabled=running()||s.dirty;
    q('#evaluationSplitField').hidden=!dataset?.partitioned;
    q('#evaluationSplit').disabled=running();
    const reviewed=dataset?.partitioned?dataset.split_reviewed?.[q('#evaluationSplit').value]:dataset?.reviewed;
    q('#evaluationRules').disabled=running()||!reviewed;
    q('#evaluationCompare').disabled=running()||!reviewed||!s.models.available||!s.chosen.size;
    q('#evaluationPrepare').disabled=running()||s.dirty;
    q('#evaluationDataset').disabled=running();
    q('#evaluationRules').title=running()?'请等待当前评测结束':!dataset?.reviewed?'请先核对至少一条通知':'';
    q('#evaluationCompare').title=running()?'请等待当前评测结束':!dataset?.reviewed?'请先核对至少一条通知':!s.models.available?'请先连接本机 Ollama':!s.chosen.size?'请先选择一个模型':'';
    q('#evaluationPrepare').title=running()?'请等待当前评测结束':s.dirty?'请先保存或放弃当前修改':'';
  }
  function models(){
    if(!active())return;
    q('#evaluationModelList').innerHTML=s.models.models.length?s.models.models.map(model=>`<label class="eval-model-option"><input type="checkbox" data-eval-model="${h(model)}" ${s.chosen.has(model)?'checked':''} ${running()?'disabled':''}>${h(model)}</label>`).join(''):`<p class="helper">${h(s.models.available?'本机尚未安装可选模型。':'未连接本机 Ollama。打开 Ollama 后刷新模型。')}</p>`;
    config();
  }
  function progress(){
    if(!active())return;
    const job=s.job, labels={idle:'尚未开始',queued:'正在准备',running:'正在评测',cancelling:'正在停止',completed:'评测完成',failed:'评测未完成',cancelled:'评测已停止'};
    q('.eval-progress-panel').hidden=['idle','completed'].includes(job.state);
    q('#evaluationJobTitle').textContent=labels[job.state]||'尚未开始';
    q('#evaluationJobDetail').textContent=running()?`${job.current_model==='rules'?'本地规则':job.current_model||''} · 已完成 ${job.completed||0}/${job.total||0} 条${job.state==='cancelling'?'；等待当前本机调用结束后停止。':''}`:job.error||(job.state==='cancelled'?'已停止，可重新开始。':'');
    q('#evaluationProgress').max=Math.max(1,job.total||1);q('#evaluationProgress').value=job.completed||0;
    q('#evaluationProgress').hidden=!running()&&job.state!=='completed';
    q('#evaluationStop').hidden=!running();q('#evaluationStop').disabled=job.state==='cancelling';
    config();modelsDisabled();
  }
  function modelsDisabled(){root?.querySelectorAll('[data-eval-model]').forEach(input=>{input.disabled=running()})}
  function history(){
    if(!active())return;
    q('#evaluationHistory').innerHTML='<option value="">选择历史评测结果</option>'+s.reports.map(r=>`<option value="${h(r.id)}" ${r.id===s.reportId?'selected':''}>${h(date(r.generated_at))} · ${r.runs>1?'AI对比':'通知评测'} · ${r.labeled} 条</option>`).join('');
    q('#evaluationDownload').disabled=!s.reportId;
    q('#evaluationDownload').title=s.reportId?'':'暂无可导出的评测报告';
  }
  function reportRows(){return s.report?.runs||s.job.results||[]}
  function chart(runs){
    const usable=runs.filter(r=>r.status!=='not_installed');
    if(!usable.length)return '';
    const values=[['task_precision','识别正确','eval-bar-precision'],['task_recall','任务找全','eval-bar-recall'],['deadline_exact','截止正确','eval-bar-deadline']];
    const maximum=Math.max(1,...usable.map(r=>r.latency_ms?.mean||0));
    return `<div class="eval-charts"><section class="panel"><h2>任务识别效果</h2><div class="eval-chart-legend">${values.map(([key,label,style])=>`<span><i class="${style}"></i>${label}</span>`).join('')}</div>${usable.map(r=>`<div class="eval-chart-row"><strong>${h(name(r))}</strong><div><svg class="eval-rate-chart" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label="${h(name(r)+values.map(([key,label])=>'，'+label+pct(r[key])).join(''))}">${values.map(([key,label,style],i)=>`<rect class="eval-bar-track" x="0" y="${i*11}" width="100" height="7" rx="1"/>${typeof r[key]==='number'?`<rect class="${style}" x="0" y="${i*11}" width="${Math.max(0,Math.min(100,r[key]*100))}" height="7" rx="1"/>`:''}`).join('')}</svg><small>${values.map(([key])=>pct(r[key])).join(' / ')}</small></div></div>`).join('')}</section><section class="panel"><h2>每条通知平均用时</h2>${usable.map(r=>`<div class="eval-time-row"><strong>${h(name(r))}</strong><span>${seconds(r.latency_ms?.mean)}</span><svg viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label="${h(name(r)+'平均用时'+seconds(r.latency_ms?.mean))}"><rect class="eval-bar-track" width="100" height="8" rx="2"/><rect class="eval-bar-precision" width="${Math.max(0,Math.min(100,(r.latency_ms?.mean||0)/maximum*100))}" height="8" rx="2"/></svg></div>`).join('')}</section></div>`;
  }
  function results(){
    if(!active()||s.tab!=='results')return;
    const runs=reportRows(),body=q('#evaluationContent');
    if(!runs.length){body.innerHTML=`<section class="panel eval-empty"><h2>${running()?'正在评测…':'还没有评测结果'}</h2><p>${running()?'完成后会在这里显示。':'核对通知后即可开始评测。'}</p>${running()?'':'<button class="button" data-eval-tab="labels">去核对通知</button>'}</section>`;return}
    const first=runs.find(r=>r.status!=='not_installed')||{},count=first.labeled||0;
    const paired=(s.report?.comparisons||[]).map(c=>(c.model||'混合方案')+'：'+({hybrid_better:'当前样本错误更少',hybrid_worse:'当前样本错误更多',tie:'当前样本持平',inconclusive:'暂无法判断'}[c.outcome]||'暂无法判断')).join('；');
    const note=[paired?paired+'。仅代表本次样本。':'',s.job.state==='cancelled'&&!s.report?'评测已停止，仅显示已完成部分。':'',`结果来自 ${count} 条已核对通知。`,count<100?'样本较少，仅供参考。':'',!first.update_cases?'延期情况尚未验证。':'',first.legacy_detection_only_cases?'旧标签只核对有无任务。':''].join('');
    body.innerHTML=`<p class="eval-result-note" role="status">${h(note)}</p>${chart(runs)}<details class="panel eval-diagnostics" id="evaluationDetails"><summary>查看问题与逐条结果</summary><div class="eval-diagnostic-summary">${runs.map(r=>`<p><strong>${h(name(r))}</strong>：${r.status==='not_installed'?'未安装，未参与评测。':`漏掉 ${r.counts?.fn||0} 项，多报 ${r.counts?.fp||0} 项${r.missing?'，原文缺失 '+r.missing+' 条':''}${r.errors?'，处理失败 '+r.errors+' 条':''}${r.model_fallbacks?'，模型失败后改用规则 '+r.model_fallbacks+' 条':''}${r.limited?'，调用达到上限 '+r.limited+' 条':''}。`}</p>`).join('')}</div><label class="eval-case-select">查看方案<select id="evaluationCaseRun">${runs.map((r,i)=>`<option value="${i}" ${i===s.caseRun?'selected':''}>${h(name(r))}</option>`).join('')}</select></label><div id="evaluationCases"></div></details>`;
    cases();
  }
  function cases(){
    if(!q('#evaluationCases'))return;
    const runs=reportRows();if(s.caseRun>=runs.length)s.caseRun=0;
    const rows=runs[s.caseRun]?.cases||[];
    const errorNames={missing_source:'原文缺失',processing_error:'处理失败',missed_task:'漏报',extra_task:'误报',wrong_deadline:'截止错误',invented_deadline:'误填截止',wrong_operation:'操作错误',model_fallback:'模型回退',processing_limit:'达到上限'};
    q('#evaluationCases').innerHTML=rows.length?`<div class="eval-scroll"><table class="eval-result-table"><thead><tr><th>消息</th><th>实际任务数</th><th>识别任务数</th><th>正确任务数</th><th>截止正确</th><th>耗时</th><th>处理方式</th><th>状态</th></tr></thead><tbody>${rows.map((r,i)=>{const issue=Boolean(r.error_types?.length)||r.status!=='evaluated'||r.matched!==r.expected||r.predicted!==r.expected||(r.deadline_cases&&r.deadline_right!==r.deadline_cases)||r.fallback||r.limited;return `<tr><td>通知 ${i+1}</td><td>${r.expected??'—'}</td><td>${r.predicted??'—'}</td><td>${r.matched??'—'}</td><td>${r.deadline_cases?`${r.deadline_right}/${r.deadline_cases}`:'未覆盖'}</td><td>${seconds(r.elapsed_ms)}</td><td>${h({rules:'规则',rules_verified:'规则校验 · 跳过模型',model_assisted:'模型辅助',relative_extension:'延期依据核对（未调用模型）'}[r.route]||'—')}</td><td><span class="pill ${issue?'amber':'green'}">${r.fallback?'模型回退':r.status==='missing'?'原文缺失':r.status==='error'?'处理错误':r.limited?'调用达到上限':issue?'需核对':'已匹配'}</span>${r.error_types?.length?`<small>${h(r.error_types.map(e=>errorNames[e]||e).join('、'))}</small>`:''}</td></tr>`}).join('')}</tbody></table></div>`:'<p class="helper">此历史报告没有逐条统计。</p>';
  }
  function selectItem(item){
    if(s.dirty&&s.item?.key!==item.key){ctx.toast('请先保存当前标注，或重新加载放弃本次修改。',true);return}
    if(s.item?.key===item.key&&s.dirty)return;
    s.item=item;s.draft=structuredClone(item.expected_tasks||[]);s.revision=s.page.revision;s.dirty=false;editor();
  }
  function labels(){
    if(!active()||s.tab!=='labels')return;
    const page=s.page;
    if(!page){q('#evaluationContent').innerHTML='<section class="panel"><p>正在读取标注消息…</p></section>';return}
    q('#evaluationContent').innerHTML=`<div class="eval-label-workspace"><section class="panel eval-message-list"><div class="panel-head"><h2>选择通知</h2><span class="helper">${page.total} 条</span></div><div id="evaluationLabelList">${page.items.map((item,i)=>`<button class="eval-message-pick ${item.key===s.item?.key?'selected':''}" data-eval-item="${h(item.key)}"><span>${page.offset+i+1}. ${h((item.display_text||item.text).slice(0,65))}</span><small>${item.reviewed?'已核对':'待核对'}${item.split?' · '+(item.split==='holdout'?'留出集':'开发集'):''}</small></button>`).join('')||'<p class="helper">尚无通知，请先导入真实消息。</p>'}</div><div class="eval-pages" ${page.total<=page.limit?'hidden':''}><button class="button" data-eval-page="${Math.max(0,page.offset-page.limit)}" ${page.offset===0?'disabled':''}>上一页</button><small>${page.total?Math.floor(page.offset/page.limit)+1:0} / ${Math.ceil(page.total/page.limit)}</small><button class="button" data-eval-page="${page.offset+page.limit}" ${page.offset+page.limit>=page.total?'disabled':''}>下一页</button></div></section><section class="panel" id="evaluationEditor"></section></div>`;
    editor();
  }
  function collect(){
    if(!q('#evaluationEditor')||s.page?.schema!==2)return;
    s.draft=Array.from(root.querySelectorAll('.eval-task-editor')).map(row=>{const value=key=>row.querySelector(`[data-answer="${key}"]`).value.trim();const task={title:value('title'),deadline:value('deadline')||null,operation:value('operation')};for(const key of ['course','scope'])if(value(key))task[key]=value(key);return task});
  }
  function editor(){
    const target=q('#evaluationEditor'),item=s.item;if(!target)return;
    if(!item){target.innerHTML='<p>从左侧选择一条通知。</p>';return}
    const legacy=s.page.schema===1;
    target.innerHTML=`<div class="panel-head"><h2>核对任务</h2><span id="evaluationDirty" class="helper">${s.dirty?'有修改尚未保存':item.reviewed?'已核对':'待核对'}</span></div><p class="helper">${h(item.course||'课程未明确')}${item.scope?' · '+h(item.scope):''} · ${h(date(item.published_at))}</p><pre class="eval-original">${h(item.display_text||item.text)}</pre>${item.display_text&&item.display_text!==item.text?`<p class="helper">${h({message:"截止依据：原消息",confirmed_task:"截止依据：当前已确认任务",candidate:"截止依据：待确认草稿，需核对",unknown:"未获取明确截止时间"}[item.deadline_source]||"截止时间需核对")}</p><details class="evidence"><summary>原始通知</summary><pre class="eval-original-raw">${h(item.text)}</pre></details>`:""}${legacy?`<p class="helper">这批旧标签只记录“${item.legacy_task?'有任务':'无任务'}”，仅供查看。请切换到收件箱通知继续核对。</p>`:`<div class="toolbar"><button class="button" id="evaluationAddTask">＋ ${s.draft.length?'再加一个任务':'添加任务'}</button><button class="text-button" id="evaluationNoTask">这条没有任务</button></div><div id="evaluationTaskEditors">${s.draft.map((task,i)=>`<fieldset class="eval-task-editor"><legend>任务 ${i+1}</legend><div class="form-grid"><label class="field">要完成什么<input data-answer="title" value="${h(task.title||'')}" maxlength="160" required></label><label class="field">截止时间（不明确可留空）<input data-answer="deadline" value="${h(task.deadline||'')}" placeholder="例如 2026-10-25" maxlength="40"></label></div><details class="eval-task-extra" ${task.operation&&task.operation!=='create'?'open':''}><summary>课程、班级或任务变更</summary><div class="form-grid"><label class="field">课程<input data-answer="course" value="${h(task.course||'')}" maxlength="100"></label><label class="field">班级<input data-answer="scope" value="${h(task.scope||'')}" maxlength="100"></label><label class="field">通知类型<select data-answer="operation">${[['create','布置新任务'],['update','延期或修改'],['cancel','取消任务']].map(([key,text])=>`<option value="${key}" ${key===task.operation?'selected':''}>${text}</option>`).join('')}</select></label></div></details><button class="text-button" data-eval-remove="${i}">移除</button></fieldset>`).join('')||'<p class="eval-no-task">没有任务可直接保存。</p>'}</div><p id="evaluationSaveError" class="error-text" role="alert"></p><div class="toolbar"><button class="button primary" id="evaluationSave">保存核对结果</button><button class="text-button" id="evaluationReloadLabel">放弃修改</button></div>`}`;
  }
  function tabs(){
    root.querySelectorAll('[data-eval-tab]').forEach(button=>button.classList.toggle('active',button.dataset.evalTab===s.tab));
    if(s.tab==='results')results();else if(s.page)labels();else loadLabels(0).catch(fail);
  }
  function fail(e){if(active())error(e.message||'操作未完成，请重试。')}
  async function loadDatasets(){
    const data=await request('datasets');s.datasets=data.datasets;
    if(!s.datasets.some(d=>d.id===s.dataset)){s.dataset=(s.datasets.find(d=>d.schema===1)||s.datasets[0])?.id||'';s.page=null;s.item=null}
    config();
  }
  async function loadModels(){s.models=await request('models');const selected=Array.from(s.chosen).filter(n=>s.models.models.includes(n));s.chosen=new Set(selected.length?selected:s.models.models.includes(s.models.preferred)?[s.models.preferred]:s.models.models.slice(0,1));models()}
  async function loadReports(pick=false){
    s.reports=(await request('reports')).reports;history();
    if(pick&&!running()&&!s.reportId&&s.reports.length){const report=s.reports.find(r=>r.runs>1)||s.reports[0];await loadReport(report.id)}
  }
  async function loadReport(id){
    if(!id)return;const n=++reportRequest,result=await request('report?id='+encodeURIComponent(id));if(n!==reportRequest)return;
    s.report=result;s.reportId=id;s.caseRun=0;history();results();
  }
  async function loadLabels(offset){
    if(!s.dataset){s.page={items:[],total:0,offset:0,limit:20,schema:2};s.item=null;labels();return}
    const id=s.dataset,n=++labelRequest,data=await request('labels?dataset='+encodeURIComponent(id)+'&offset='+offset);
    if(n!==labelRequest||id!==s.dataset||s.saving)return;s.page=data;
    if(!s.dirty){s.item=data.items.find(item=>item.key===s.item?.key)||data.items[0]||null;s.draft=structuredClone(s.item?.expected_tasks||[]);s.revision=data.revision}
    labels();
  }
  async function poll(){
    clearTimeout(timer);if(!active())return;
    try{
      const job=await request('runs');if(!active())return;s.job=job;progress();
      if(running()){s.report=null;s.reportId='';history();results()}
      else if(job.state==='completed'&&job.report_id&&job.report_id!==s.reportId){await loadReports();await loadReport(job.report_id)}
      else if(job.state==='cancelled'){s.report=null;s.reportId='';results()}
      if(running())timer=setTimeout(poll,1500);
    }catch(e){fail(e);if(active())timer=setTimeout(poll,4000)}
  }
  async function download(path,filename){const response=await ctx.api('/api/evaluation/'+path);const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  async function click(event){
    const button=event.target.closest('button');if(!button||!root.contains(button)||button.disabled)return;
    const pending=['evaluationRules','evaluationCompare','evaluationStop','evaluationModelsRefresh','evaluationPrepare','evaluationHoldout','evaluationDownload','evaluationSave','evaluationReloadLabel'].includes(button.id);
    if(pending){button.disabled=true;button.setAttribute('aria-busy','true')}
    try{
      error();
      if(button.dataset.evalTab){
        if(button.dataset.evalTab==='labels'&&!s.dirty&&s.datasets.find(d=>d.id===s.dataset)?.schema===1){
          const editable=s.datasets.find(d=>d.schema===2);if(editable){s.dataset=editable.id;s.page=null;s.item=null;config()}
        }
        s.tab=button.dataset.evalTab;tabs();return;
      }
      if(button.hasAttribute('data-eval-item')){selectItem(s.page.items.find(item=>item.key===button.dataset.evalItem));labels();return}
      if(button.hasAttribute('data-eval-page')){if(s.dirty)throw Error('请先保存当前标注。');await loadLabels(Number(button.dataset.evalPage));return}
      if(button.hasAttribute('data-eval-remove')){collect();s.draft.splice(Number(button.dataset.evalRemove),1);s.dirty=true;editor();return}
      switch(button.id){
        case 'evaluationRules':case 'evaluationCompare':{
          button.disabled=true;s.report=null;s.reportId='';s.job=await post('runs',{dataset:s.dataset,mode:button.id==='evaluationRules'?'rules':'compare',models:Array.from(s.chosen),...(s.datasets.find(d=>d.id===s.dataset)?.partitioned?{split:q('#evaluationSplit').value}:{})});s.tab='results';tabs();history();progress();poll();break;
        }
        case 'evaluationStop':s.job=await post('cancel',{id:s.job.id});progress();break;
        case 'evaluationModelsRefresh':await loadModels();break;
        case 'evaluationHoldout':
        case 'evaluationPrepare':{
          if(s.dirty)throw Error('请先保存当前标注。');button.disabled=true;const result=await post('datasets',{limit:200,...(button.id==='evaluationHoldout'?{holdout:true}:{})});s.dataset=result.id;s.page=null;s.item=null;s.tab='labels';await loadDatasets();tabs();await loadLabels(0);ctx.toast(`已选取 ${result.prepared} 条通知，核对后可开始评测。`);break;
        }
        case 'evaluationDownload':await download('report?id='+encodeURIComponent(s.reportId)+'&download=1','courseinbox-evaluation.json');break;
        case 'evaluationAddTask':collect();if(s.draft.length>=20)throw Error('每条通知最多20个任务。');s.draft.push({title:'',deadline:null,operation:'create'});s.dirty=true;editor();break;
        case 'evaluationNoTask':s.draft=[];s.dirty=true;editor();break;
        case 'evaluationReloadLabel':s.dirty=false;await loadLabels(s.page?.offset||0);break;
        case 'evaluationSave':{
          if(s.saving)break;collect();button.disabled=true;s.saving=true;labelRequest++;
          const submitted={dataset:s.dataset,key:s.item.key,revision:s.revision,reviewed:true,expected_tasks:structuredClone(s.draft)};
          let saveError='';
          try{
            const result=await post('labels',submitted);
            labelRequest++;
            if(s.dataset===submitted.dataset){
              s.revision=result.revision;if(s.page)s.page.revision=result.revision;
              const saved=s.page?.items.find(item=>item.key===submitted.key);
              if(saved){saved.reviewed=true;saved.expected_tasks=structuredClone(submitted.expected_tasks)}
              if(s.item?.key===submitted.key){s.item.reviewed=true;s.item.expected_tasks=structuredClone(submitted.expected_tasks);if(JSON.stringify(s.draft)===JSON.stringify(submitted.expected_tasks))s.dirty=false}
            }
            await loadDatasets();ctx.toast(s.dirty?'已保存提交时的答案；当前修改尚未保存。':'核对结果已保存。');
          }catch(e){saveError=e.message}
          finally{s.saving=false;labels();if(saveError){if(q('#evaluationSaveError'))q('#evaluationSaveError').textContent=saveError;else error(saveError)}}break;
        }
      }
    }catch(e){fail(e);config()}
    finally{if(pending){button.disabled=false;button.removeAttribute('aria-busy');if(active()){config();history();q('#evaluationStop').disabled=s.job.state==='cancelling'}}}
  }
  function change(event){
    const input=event.target;
    if(input.id==='evaluationDataset'){
      if(s.dirty){input.value=s.dataset;ctx.toast('请先保存当前标注，或重新加载放弃修改。',true);return}
      s.dataset=input.value;s.page=null;s.item=null;config();if(s.tab==='labels')loadLabels(0).catch(fail);
    }else if(input.id==='evaluationSplit'){config();
    }else if(input.hasAttribute('data-eval-model')){if(input.checked)s.chosen.add(input.dataset.evalModel);else s.chosen.delete(input.dataset.evalModel);config()}
    else if(input.id==='evaluationHistory')loadReport(input.value).catch(fail);
    else if(input.id==='evaluationCaseRun'){s.caseRun=Number(input.value);cases()}
  }
  function mount(container,context){
    ctx=context;if(container.querySelector('#evaluationRoot'))return;
    generation++;const version=generation;
    container.innerHTML=ctx.intro('识别评测','看看通知里的任务有没有识别准确。','')+`<div id="evaluationRoot"><p id="evaluationError" class="error-text" role="alert"></p><section class="panel eval-config"><div class="eval-config-heading"><label class="field">评测通知<select id="evaluationDataset"><option>正在读取…</option></select></label><button class="button primary" id="evaluationRules">开始评测</button></div><p id="evaluationDatasetSummary" class="helper"></p><details id="evaluationOptions" class="eval-options"><summary>更多选项</summary><div class="eval-option-grid"><section><h3>AI 对比（可选）</h3><div id="evaluationModelList"><p class="helper">正在检查本机模型…</p></div><div class="toolbar"><button class="button" id="evaluationCompare">开始 AI 对比</button><button class="text-button" id="evaluationModelsRefresh">刷新模型</button></div></section><section><h3>通知与记录</h3><button class="button" id="evaluationHoldout">新建独立评测集</button><label class="field" id="evaluationSplitField" hidden>评测范围<select id="evaluationSplit"><option value="holdout">留出集（验证效果）</option><option value="development">开发集（调参）</option></select></label><button class="button" id="evaluationPrepare">从收件箱选取通知</button><label class="field eval-history">过去的结果<select id="evaluationHistory"><option value="">选择历史结果</option></select></label><button class="text-button" id="evaluationDownload">导出当前报告</button></section></div></details></section><section class="eval-progress-panel" aria-live="polite" hidden><div><strong id="evaluationJobTitle"></strong><p id="evaluationJobDetail" class="helper"></p></div><progress id="evaluationProgress" value="0" max="1" hidden></progress><button class="button" id="evaluationStop" hidden>停止评测</button></section><div class="eval-navigation"><div class="section-tabs"><button class="section-tab" data-eval-tab="results">评测结果</button><button class="section-tab" data-eval-tab="labels">核对通知</button></div></div><div id="evaluationContent"></div></div>`;
    root=container.querySelector('#evaluationRoot');root.addEventListener('click',click);root.addEventListener('change',change);root.addEventListener('input',event=>{if(event.target.hasAttribute('data-answer')){collect();s.dirty=true;if(q('#evaluationDirty'))q('#evaluationDirty').textContent='有修改尚未保存'}});
    config();history();tabs();progress();
    loadDatasets().then(()=>{if(version!==generation)return;config();if(s.tab==='labels')loadLabels(s.page?.offset||0).catch(fail)}).catch(fail);
    loadReports(true).catch(fail);loadModels().catch(fail);poll();
  }
  function unmount(){if(root){generation++;clearTimeout(timer);root=null}}
  window.addEventListener('beforeunload',event=>{if(s.dirty){event.preventDefault();event.returnValue=''}});
  return {mount,unmount};
})();
