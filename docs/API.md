# CourseInbox API v0.1

## 本机网页评测

所有 `/api/evaluation/` 接口要求主访问令牌、本机回环客户端及 Host、同源请求；手机/正文同步派生令牌不能调用。仅操作本机评测文件与只读数据库快照，不写消息或任务。

- `GET /datasets` 列出现有有效标签；`POST /datasets {limit: 1..200}` 从真实消息准备未核对工作文件。
- `GET /labels?dataset=文件名&offset=0&limit=20` 返回分页原文和人工答案；`export=1` 下载已核对标签，剔除辅助原文。
- `POST /labels {dataset,key,revision,reviewed,expected_tasks}` 原子保存人工答案，旧 revision 返回409，非法任务/日期返回400。
- `GET /models` 查询本机 Ollama 已安装模型；不下载、不更改模型配置。
- `POST /runs {dataset,mode:"rules"|"compare",models:[]}` 启动后台评测，同一时间仅一项（冲突409），compare最多三个已安装模型。仅评分已核对标签，比较使用相同只读快照。
- `GET /runs[?id=编号]` 查询进度与取消/失败状态；`POST /cancel {id}` 请求停止，当前模型调用结束后生效。切换网页不停止后台任务，服务退出终止未完成任务。
- `GET /reports` 列出历史报告；`GET /report?id=编号[&download=1]` 返回仅含指标/消息哈希的报告，网页报告持久化在 `data/evaluation/`。

上述简写路径均接在 `/api/evaluation` 后。数据集与报告只能选服务列出的编号，禁止任意路径。标注改变后须重新运行才生成新成绩；旧报告保留原版本。

## 学习通网页正文接口

- `GET /api/chaoxing/pairing`：必须使用主访问令牌，并从本机回环地址访问；返回仅用于写入网页正文的派生令牌及本机地址。不能从扩展来源或局域网获取。
- `POST /api/chaoxing/messages`：必须使用网页同步专用令牌，只允许本机回环地址；后台扩展来源 `chrome-extension://<32位扩展ID>` 可写入此唯一接口，其余 API 的来源校验保持严格。
- `GET /downloads/courseinbox-browser-companion.zip`：只下载固定名称的已打包源码 ZIP，不含任何令牌。
- `GET /api/settings` 新增 `chaoxing_web`：最近消息记录中的网页正文数量及最近接收时间，不含专用令牌。

网页正文请求示例：

```json
{
  "message_id": "example-message-1",
  "text": "测试正文，不是真实学生记录",
  "conversation": "示例会话",
  "sender": "示例同学",
  "display_time": "昨天 23:22",
  "captured_at": "2026-10-05T23:22:00+08:00",
  "direction": "received"
}
```

响应只返回 `{"accepted":true,"duplicate":false}`；重放同一编号返回 200、duplicate=true，不返回已有正文或草稿。新消息返回201。不同消息编号即使文字相同也分别保存。首次保存的文字作为来源证据，不同步后续编辑或删除。

无法识别网页时间时传 captured_at=null，保留 display_time；正文仍保存，但不产生任务草稿，也不允许以接收时间重新提取。规则提取失败会保存正文并附 extraction_warning，防止堵塞后续同步。网页正文元数据保存于消息 external 字段，正常主令牌读取消息时可见；仅能写入的专用令牌不能读取这些字段。

默认服务 `http://127.0.0.1:8765`。除 health、静态页面、固定 APK 下载、只读 pairing 和回环 bootstrap 外，所有接口都需要 `Authorization: Bearer <data/access-token.txt>`。JSON POST/PATCH 使用 `Content-Type: application/json`。

浏览器 Origin 必须为当前服务同源；Host 必须为本机地址和服务端口。普通远程浏览器无法调用 bootstrap 取令牌，需手动输入已有令牌。服务默认仅回环监听，局域网显式启动。

## 读取

- `GET /api/health`：健康状态。
- `GET /api/bootstrap`：只向本机回环、合法 Host 的请求提供访问令牌，禁止缓存。
- `GET /api/state`：任务、待确认草稿、历史归档 `archived_proposals`、最近消息记录、可见消息总数 `message_total`、摘要和实际运行模式。
- `GET /api/tasks`，`GET /api/tasks/{id}`：列表与详情（来源 / 变更历史）。
- `GET /api/messages`：按原发布时间排列的最近500条可见消息；发布时间未知时用接收时间。
- `GET /api/messages/page?limit=50&offset=0`：分页返回 `{items,total,limit,offset}`；limit 为1–200。
- `GET /api/messages/{id}`：消息原文，包含为任务或草稿保留但已从消息列表清理的来源。只读返回 `timing` 和 `related`：`tasks` 为通过来源表实际关联的已确认任务摘要（id/title/course/scope/deadline/status），不含合并或排除记录；`proposals` 为通过主消息或补充证据关联的 pending/archived/dismissed 草稿摘要（id/title/course/deadline/action/status）。查看详情不确认草稿、不修改任务。附件读取状态和原始正文仍保存在 `external`，不能用已关联任务替代读取成功。
- `GET /api/messages/cleanup-preview`：当前可见消息ID快照 `{ids,count,total}`，每批最多10000条；不返回正文。
- `GET /api/proposals`：待确认草稿。
- `GET /api/dashboard`：尚未提交、已提交、7天截止、逾期及提醒。
- `GET /api/settings`：应用白名单、运行模式、监听地址，不包含模型密钥。
- `GET /api/calendar.ics`：日历文件，不含取消任务。
- `GET /api/export.json`：记录导出，不含访问令牌；没有导入恢复 API。

## 导入与确认

`POST /api/messages`：

```json
{
  "text":"《软件工程》 第三次作业：请提交实验报告、源代码。截止：10月12日 23:59。",
  "source":"学习通",
  "captured_at":"2026-10-03T16:00:00+08:00",
  "course":"",
  "scope":"计科1班",
  "mode":"rules"
}
```

mode 为 rules / agent / default。默认按服务端配置。明确 agent 但未配置模型返回400，模型失败返回502。文本最多30000字。201为新增，200 + duplicate=true为重放。返回 message、proposals、mode、trace；这一步不创建任务。

草稿包含 candidate（title/course/scope/deadline/kind/requirements/submission_method/teacher/source_url/platform_status/confidence/field_evidence/operation/evidence/warnings）、action（create/update/merge/conflict/cancel；兼容旧 link）、target_id、expected_version、before。kind 额外支持 presentation。

等价来源可返回同一个草稿 ID；`source_count`、`source_message_ids` 表示其全部原文。不同截止或材料要求的版本不静默折叠。`duplicate_review` 为待核对的已有任务，元素含 task_id/title/course/scope/version/reason；reason 为 possible_duplicate 或 conflicting_identity。疑似重复仍保存消息原文，普通确认返回 409；相似度仅用于提示核对，不自动选择目标。

`POST /api/proposals/{id}/confirm`，JSON对象为可选编辑字段：title、course、scope、deadline、kind、requirements、submission_method。冲突草稿另须提供 `resolution:"current"` 或 `resolution:"incoming"`。已有目标的名称、课程、班级不可改，需重新导入重新匹配。MERGE 合并补充要求和缺失字段；显式编辑按 UPDATE 执行；冲突决议及实际动作写入历史。

截止变更通知必须匹配到原任务后才能确认；未匹配时接口拒绝把它创建成新作业。可在草稿中核对并修正任务名称、课程、班级，使其匹配已有任务，再提交 `expected_version`；截止变更原文未识别出新日期时，需先填写新截止日期。

疑似重复可提交 `{"link_only_to":"已核对任务ID","expected_version":1}`，只关联全部原文并记录历史，保留已有截止、要求和进度。目标必须属于服务端当前核对候选；来源编号冲突时禁止此操作。版本过期或身份已被其他任务占用均返回 409。完整学习通课程/班级/作业或考试编号由数据库唯一登记；创建、关联和登记在同一即时事务提交，不能通过并发确认或 matchable=false 创建副本。

截止为 `YYYY-MM-DD` 或带时区 ISO 时间；缺失用 null。requirements 为任务要求字符串列表，包括阅读、预习、研讨准备或提交材料；附件细则未导入时明确提示待核对。确认幂等，过期版本和较旧消息覆盖返回409，任务不变。

`POST /api/messages/{id}/reanalyze`：空对象或 `{ "mode":"rules" }`，按原文及原发布时间重新规则提取；保留消息ID，旧待确认/归档草稿变为已忽略，生成使用当前任务版本的新草稿。人工恢复不再次自动归档；已确认任务、已确认草稿和历史不改变。可用来恢复状态更新后的过期草稿，不必伪造原文或时间。

重新识别组内任一消息或补读附件时，保留匹配任务的整组来源与身份依据；关键字段等价时沿用最新来源及其真实原文时间，防止刷新较旧成员后被误判为历史覆盖。作业考试中心的结构化标题、编号及截止在重新识别时保留。

`POST /api/messages/clear`：`{ "ids":["32位消息ID"] }`，仅清理确认前选定的快照，返回 `{cleared,preserved,deleted}`。保留任务和待确认草稿的原文但隐藏列表条目；删除无关联消息正文，长期保存轻量去重指纹。隐藏来源仍可接收同一通知的安全附件补读，列表不会重新出现。该接口不清理学习通平台数据。

## 电脑后台提醒与重新检查

下列提醒接口仅允许本机回环地址和主访问令牌，网页同步专用令牌不能调用：

- `GET /api/desktop/alerts`：`{enabled,events:[{id,kind,title,body,url}]}`，最多20条未确认投递事件；首次已有内容作为基线。学习通作业中心按课程/班级/列表建立初始盘点基线，失败课程不阻塞其他课程。
- `POST /api/desktop/alerts/ack`：`{ids:["事件ID"]}`，Windows成功接收投递后才调用；回执持久化。失败投递不确认。
- `POST /api/desktop/alerts/settings`：`{enabled:true}`，保存提醒开关；重新开启不重放关闭期间的积压。
- 提醒链接限定为同一本机服务根页面 `/?message=<32位ID>#inbox` 或 `/?task=<32位ID>#tasks`。
- `POST /api/chaoxing/desktop/recheck`：空对象，复用当前会话，补传本地队列并请求三来源重新检查；不强制重新扫码。

同步状态新增 `worker_alive/last_heartbeat/restart_count/next_retry_at/freshness/inventory_epoch`。各来源提供 `last_progress/last_complete_success/freshness/coverage/detail_pending_count/unsupported_detail_count/media_pending_count`；通知另有 `attachment_pending_count`。`discovered_sections` 是首次枚举的课程列表匿名key，与详情完整性分开；扫码/退出变更代次，普通恢复保留。仅上次检查成功或后台仍在运行，不代表详情、附件和媒体已完整读取。
`POST /api/proposals/{id}/dismiss` 忽略草稿，原消息保留。

`PATCH /api/tasks/{id}`：

```json
{"status":"done","checklist":[true,false],"expected_version":1}
```

字段都可选。checklist为与当前材料数等长的布尔数组。状态：pending/in_progress/done/submitted/cancelled。建议带expected_version避免并发覆盖。done仍提示提交；submitted为手动确认。

## 文件与助手

`POST /api/files/extract`：`{"filename":"notice.png","content_base64":"..."}`。文件最大8 MB，请求最大12 MB。返回text、engine、needs_review，不直接导入任务。PNG/JPG/BMP使用Windows OCR；TXT/MD需UTF-8；PDF需可选pypdf，最多30页；DOCX读取本地正文及表格，不执行文档内容。

`POST /api/assistant`：`{"question":"我有哪些待提交任务？","course":"软件工程","scope":"计科1班"}`。scope为null时查询全部班级。仅有读取工具，不直接写任务。返回answer、mode、trace、limited。

`POST /api/settings`：`{"allowed_packages":["com.chaoxing.mobile"]}`，最多30个包名。电脑接收和手机采集两端都要设置。
`POST /api/demo` 加载明确标注的合成示例；不会向学习平台取数据。

## Android 通知事件

`POST /api/mobile/notifications`：

```json
{
  "package_name":"com.chaoxing.mobile",
  "notification_key":"0|com.chaoxing.mobile|123|tag|10001",
  "title":"《软件工程》 第三次作业",
  "text":"请明天18:00前提交实验报告。",
  "captured_at":"2026-10-03T08:00:00Z",
  "scope":"计科1班",
  "course":""
}
```

captured_at 必填，使用通知的postTime，不用上传时间替代。package必须在白名单。只持久化和生成规则草稿，不自动确认，也不把后台通知发送至外部模型。

手机遇到200/201才移除本地事件；401/403或网络失败留在队列。重复事件返回200、duplicate=true，内容改变生成新的消息。来源为 `Android · 包名`。

## 错误

返回 `{"error":"可读说明"}`。400输入无效、401缺令牌、403来源/Host/应用未授权、404不存在、409版本冲突、502模型问题、500内部异常。令牌不出现在URL、工具结果或消息日志。

## 手机配对与发现（0.2.0）

LAN 模式公布 DNS-SD `_courseinbox._tcp.local.`；TXT 仅含 version、device_id、name。身份保存在 data/mobile-device.json。

`GET /api/mobile/pairing?challenge=<64位小写十六进制nonce>` 是不携带令牌的只读请求，仍经过 Host / Origin 校验。响应为 version=1、device_id、name、challenge、address、port、proof；address 为校验通过的目标 IPv4。proof 是以访问令牌为密钥的 HMAC-SHA256，小写十六进制。消息是 UTF-8 的五行：courseinbox-pair-v1、device_id、challenge、address、十进制 port；LF 分隔，无尾部 LF。

手机在 challenge、目标地址、端口、已配对身份及摘要全部通过后才向该端点携带 Bearer 发送通知。初次显式配对允许保存身份，普通补传不能更换身份。`GET /api/settings` 的 mobile_discovery 含固定名、身份、可用性、原因及当前地址，需要 Bearer 授权，不含令牌。

`GET /downloads/courseinbox-companion-0.2.2-debug.apk` 提供固定名称的安装包下载，不包含令牌。其他下载路径仍返回404。


## 学习通网页课程通知（浏览器组件0.2.0）

### 桌面任务核对与补收

以下两个端点仅允许本机回环、主访问令牌及受信来源；网页组件令牌无权调用。

- `GET /api/chaoxing/desktop/inventory?limit=20&offset=0`：只读对照已观察的平台清单与本地原文内容版本。limit为1–100，offset为非负整数；返回items、total、counts、sections、unchecked_sections、detail_pending、manual_details、catalog_limited及分页参数。条目state为missing/unrecognized/pending/confirmed/archived/ignored/cleared，detail_state为read/pending/manual；confirmed表示原文已经关联本地任务。栏目state为unchecked/partial/failed/checked；freshness为fresh/unverified，重启后需重新检查。清单包含本地课程/标题/编号，不能作为无正文的检查报告导出。
- `POST /api/chaoxing/desktop/repair`：空对象安排最多50项任务缺口补收；或传`{"keys":["课程编号|班级编号|assignment或exam|任务编号"]}`定向补收，或传`{"sections":["课程编号|班级编号|assignment或exam"]}`重试已知栏目，两类参数不能同时提供。编号必须来自当前清单，不接受任意平台URL。返回requested、reextracted、sections_requested，表示已安排数量，不代表平台读取成功。暂停时返回400，需先恢复同步。已忽略、归档及清理记录不自动恢复；真实变化仍遵循原有确认与版本保护。

后台每次维护最多安排5个任务及2个未完成栏目；任务按10/20/40/60秒退避，栏目间隔至少60秒。采集器优先处理相关课程，但每轮仍轮转普通课程，每个栏目详情预算仍为5项。清单元数据保存在`data/chaoxing-sync/task-inventory.json`；不保存新的账号凭据，退出账号或重新扫码时重建清单，既有消息与任务保留。

`GET /api/chaoxing/pairing`：仅本机、主访问令牌授权，返回独立网页同步令牌。该令牌不能读取本地消息或配置。浏览器无需向电脑提供学习通账号、密码、Cookie。

`POST /api/chaoxing/messages`：仅回环及专用令牌，可接受合法扩展 Origin。聊天协议仍为 message_id/text/conversation/sender/display_time/captured_at/direction。课程通知额外提供 `kind:"course_notice"`、title、course、url、attachments；direction仅received。通知url限官方HTTPS详情路径且不含query，附件url仅空值或已验证固定下载域及32位资源编号。

作业/考试中心使用 `kind:"task_center"`，额外提供 title、course、task_type、deadline、submission_method、platform_status、teacher、url、field_evidence。url 仅允许 `mooc1.chaoxing.com` 或 `mooc2-ans.chaoxing.com` 的 HTTPS 页面；平台状态只保留为来源证据，不直接修改本地任务状态。

attachments最多20项，每项name(180)、url、size(整数)、status、text(20,000)、error(250)。可选kind仅接受inline_image，此时url仅允许HTTPS的p.ananas.chaoxing.com图片路径（PNG/JPG/BMP/WebP，无片段）；其余附件保持固定下载域限制。课程通知还可提供media_pending_count（0–1000整数），表示未支持的媒体数。status为listed/extracted/partial/failed/skipped，只有extracted/partial可含正文。通知标题、原正文、附件列表及提取文字组合最多30,000字符。来源“学习通网页 · 课程通知”；external.notice_body单独保留原正文。无法识别发布时间时captured_at传null，time_known=false，不生成相对日期草稿。通知重放200，新消息201，响应accepted/duplicate，不直接确认任务。

附件失败后重试成功，可在同一通知ID、同一原正文/标题/时间/附件身份下补齐附件文字，并在原附件清单末尾追加迟发现的inline_image；刷新待确认草稿，已确认任务不改变。已提取文字不会降级，正文编辑不会覆盖原证据。

`POST /api/chaoxing/attachments/extract`：同一回环/专用令牌边界，输入filename/content_base64，支持DOCX、PDF、TXT/MD、PNG/JPG/BMP/WebP，文件最大8MiB。返回text(最多20,000)、engine、truncated。扫描PDF由Windows本地识别，engine为windows-pdf-ocr，部分读取后缀/partial且truncated=true；最多30页，每次OCR最多前10页。只提取上传的文档，不访问平台URL，不存文档二进制，不提供读取本地其他记录的能力。普通文件提取接口同时返回partial布尔值供导入界面显示。

`GET /api/settings`的chaoxing_web包含received_count、chat_count、course_notice_count、task_center_count、latest_received_at（最多最近500条记录范围）。`GET /downloads/courseinbox-browser-companion.zip` 提供0.3.0组件固定11文件安装包，不包含令牌。

`POST /api/chaoxing/desktop/logout`：仅限本机回环、主访问令牌和受信来源；请求体必须为空对象。停止独立浏览器 worker，删除本机加密学习通会话、二维码和连接诊断，不删除已接收消息、任务、草稿、附件状态或去重记录。重复调用保持幂等。

附件ACK可附attachment_pending=true（已保存记录仍有失败附件）或attachment_conflict=true（完整提取与旧部分文字不一致）；浏览器保留待补齐job，不以单纯200重放清除。部分文字只允许被包含原前缀的完整文字补齐。


## 学习通后台同步（Windows）

`GET /api/tasks`、`GET /api/state` 与任务详情中的 `platform_check` 为最近的平台观察值，包含 status、checked_at、source_url、observation_id、suggested_status、detail_state、detail_error。它与本地 status 分开；重复扫描不修改任务版本，不据此自动提交或更改进度。

`POST /api/tasks/{id}/adopt-platform-status`：主令牌调用，JSON 为 `{"expected_version":1,"observation_id":"当前观察标识"}`。核对记录和任务版本均须一致且不超过 24 小时；用户确认后更新本地状态并记录 platform_status_confirmed 历史。未知/混合平台状态不能直接采用；组件专用令牌不能调用此入口。

task_center 接入可附 description、attachments（最多20项，name/url/status及可选size/text/error/kind）、detail_state（list_only/read/skipped/unavailable）及 detail_error。普通附件只接受现有固定官方下载地址；kind=inline_image 的图片接受已适配的 p.ananas.chaoxing.com 图片地址并进入OCR。status为listed/extracted/partial/failed/skipped，正文非空时必须extracted或partial，完整提取状态必须有正文。任务说明附件复用下载和文字提取链路，正文进入原消息及待确认要求，失败/部分/未支持状态保持缺口。同一任务观察中，附件清单与原文一致时仅做单调补全；不兼容文字保留旧文并返回attachment_conflict，不自动确认任务。

任务清单条目新增 deadline、deadline_pending、detail_error，汇总新增 deadline_pending 与 attention_deadline_pending。正文已读但截止原文缺少年份时保持 deadline=null 并记录待核对；验收接口也将此缺口计入，不能仅凭正文读取成功判为完整。长要求按清单单项180字、最多30项分段，超出部分仍保留在消息原文并提示核对。

可选detail_url必须是原任务同课程、班级和作业编号的官方只读work/view或work/detail链接，不接受answer/submit/start等操作参数及考试入口。该链接由已渲染列表明确提供，原url继续保留；后台不猜测替换URL。详情页禁用脚本并限制为同任务只读导航，图片/样式/XHR等资源不能绕过写操作限制。标题空壳、脚本动态内容及未支持附件继续要求人工核对。

task_center 还可附 published_at（YYYY-MM-DD 或带时区的 ISO 时间）及 field_evidence.published_at。captured_at 继续表示本次平台观察时间，供状态新鲜度与防回退使用；不能据此声称任务发布时间。后来补齐同一内容版本的明确发布时间不会新建消息、改变正文或自动修改任务。

消息 GET 接口和 /api/state 的消息项附只读 timing：published_at、publication_source（platform/message/notice/unknown）、deadline、deadline_source（message/confirmed_task/candidate/unknown）。消息分页按这个发布时间倒序，未知排后；发布通知和已确认任务只在来源关系或完整平台身份唯一时提供补充依据，候选截止明确标为待核对。未获取的时间为null。原始消息、内部接收/观察时间与确认历史继续保留。

以下接口仅允许回环地址、受信 Origin/Host 和主访问令牌，网页组件专用令牌不可调用。

- `GET /api/chaoxing/desktop/status`：返回 enabled、state、qr_ready、session_saved、last_success、last_error、queued、incomplete、last_count、error_stage、error_code、retry_in、sources；sources 中 chat/notice/task_center 分别包含 state、last_checked、last_success、checked_count、captured_count、failed_count、pending_count 和固定枚举映射的 error/stage/reason。作业/考试失败项还以 `issue_summary` 表示课程序号与入口类型；一个来源的成功不会覆盖另一个来源的失败。诊断不返回学习通 Cookie、登录 URL、二维码内容或会话文件路径。
- `GET /api/chaoxing/desktop/acceptance`：只读JSON下载，检查worker新鲜度、队列、各来源完整覆盖、数据库完整性、重复平台身份和提醒开关；包含计数和人工验收项目，不含消息正文、学习通链接或凭据。automated_ready仅反映当前自动检查，real_acceptance固定pending，不能据此声称真实发布或Windows通知显示已验证；组件专用令牌被拒绝。
- `POST /api/chaoxing/desktop/login`：空对象启动全新独立会话获取官方二维码；可传 `{"visible":true}` 打开首次验证窗口，验证后转为后台会话。不会导入现有浏览器状态。
- `POST /api/chaoxing/desktop/resume`：空对象，复用当前 Windows 用户 DPAPI 加密会话，先补传文本队列，再恢复后台扫描。
- `POST /api/chaoxing/desktop/pause`：空对象，持久化关闭状态并停止后台浏览器，不删除加密会话。
- `GET /api/chaoxing/desktop/qr`：扫码等待期间返回 PNG，需主令牌 Header，暂停、失效或不在扫码状态时404；响应不缓存。前端使用授权请求后的 Blob URL 显示，令牌不进入 URL。

state 为 idle/connecting/waiting_scan/connected/syncing/expired/paused/error/retrying/partial。retrying保留登录并以10/20/40/60秒间隔重试，partial表示部分通知读取失败且其他消息继续；resume也可用于立即重试现有加密会话。约每分钟读取官方已加载课程收件通知列表，复用既有课程通知校验、时间解析与附件证据补齐协议。没有自动确认任务、提交作业或绕过平台授权。


## 用户补充详情

- `GET /api/messages/{id}/supplements`：主访问令牌鉴权，读取原消息允许的目标及人工补充记录。目标为已关联 `task:{id}`、该消息的 `proposal:{id}`，结构化任务无草稿时为 `source`；没有可关联任务时选择 `auto` 识别补充正文。返回 `reference_at/reference_known` 作为相对日期依据。
- `POST /api/messages/{id}/supplements`：`text`（必填，最多20000字）、`target`（必填，必须来自上述目标）、`reference_at`（可选，原通知时间未知时必填）、`filename`（可选，最多200字）、`file_partial`（可选布尔）。新记录201，完全相同请求重放200；不接受外部任务链接或任意目标字段。
- 截图/附件先复用 `POST /api/files/extract` 的8MB本地提取接口，用户核对提取文字后提交。提取失败保留编辑内容；原文件字节不写入消息数据库。
- 新增独立消息及 `message_supplements` 关联行，原消息正文/时间不变。生成草稿并关联原证据，仍通过既有 `/api/proposals/{id}/confirm` 人工确认。补充不能跳过身份、字段冲突或版本检查。旧通知允许确认追加要求，但不能覆盖较新来源字段。
- `GET /api/chaoxing/desktop/inventory` 的单项增加可空 `manual_supplement`，包含 `count/status/file_partial`。人工补充状态与自动 `detail_state/media_pending/manual_details` 分开，不能据此报告平台已完整读取。备份SQLite包含新关联表，JSON导出的消息包含补充元数据及其原消息编号。

## 电脑到手机浏览器的局域网提醒

控制接口仅允许回环、主访问令牌和受信来源；网页组件令牌无权调用：

- `GET /api/mobile-reminders/status`：返回 enabled/listening/port/addresses/server_id/error/android_version，以及设备 id/name/paired_at/last_seen/online，不含设备令牌或配对码。
- `POST /api/mobile-reminders/settings`：`{"enabled":true}` 开启独立 IPv4 提醒监听器，默认 8766；false 关闭。开关持久化，重启恢复。主服务继续仅本机。
- `POST /api/mobile-reminders/pairing`：空对象生成六位、五分钟、单次配对码。每 IP 每个码最多尝试五次，合计二十次。
- `POST /api/mobile-reminders/revoke`：`{"id":"32位设备编号"}` 立即删除设备和回执，使旧令牌失效。

独立监听器仅接受回环或私有 IPv4 客户端，校验 Host/Origin，不提供主管理 API、CORS、凭据读取或任意文件下载。最多 32 个并发处理、连接读取超时八秒。只提供：

- `GET /v1/health` → app/version/server_id。
- `POST /v1/pair`：`{"code":"六位码","name":"设备名"}` → token/device_id/server_id，最多十台。服务端仅存 SHA256 设备令牌摘要。
- `GET /v1/alerts`：Bearer 设备令牌 → enabled/server_id/events/poll_after。每批最多二十条，事件含 id/kind/title/body/url；手机忽略远端 url，只打开本地历史。
- `POST /v1/ack`：同一令牌，`{"ids":["事件编号"]}`，每批最多一百，仅能确认本设备已发出的事件。JSON 上限 32 KiB；配对请求上限 4 KiB。
- 固定下载白名单 `/downloads/courseinbox-learning-0.3.21-debug.apk` 与 `/downloads/courseinbox-learning-0.3.21-arm64-debug.apk`，APK 不含配对凭据。

设备回执独立于桌面与其他手机。配对时已有事件建立基线；新课程初次盘点完成时间持久化在 source_section_times。未完成首轮的任务暂缓投递，完成后只基线此前观察到的存量；稍后新增内容可在手机恢复后投递。截止规则复用桌面判定，不受桌面提醒开关或桌面回执影响。手机通知成功并保存独立 SQLite 日志后确认，重放使用稳定 tag/id；停止、重新配对有代次保护。关闭服务保留配对及回执，撤销才删除设备。


浏览器入口为受限8766监听器的 `GET /`，固定静态资源仅 `/phone.js`、`/phone.css`。未配对可加载页面与健康检查；消息接口仍需独立设备Bearer。固定CSP只允许同源脚本、样式与连接，拒绝嵌入，不加载主管理app.js或主访问令牌。手机网页用同源v1配对、提醒与回执，不需要APK。

配对与提醒日志保存在本Origin的localStorage，停止、断开、重配有持久化控制版本和跨标签同步，异步结果在落盘/显示/回执前核对版本。前台网页显示成功并保存后才确认，隐藏页面暂缓消费。当前HTTP网页不提供浏览器系统后台推送；关闭/锁屏可能暂停，返回补收。提示音受浏览器策略限制。Android接收端为可选客户端，共用既有v1协议。
