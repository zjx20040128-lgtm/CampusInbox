package cn.courseinbox.companion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebStorage;
import android.widget.*;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions;
import java.io.File;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

/** Standalone mobile inbox; the paired-computer workflow remains an optional screen. */
public final class MainActivity extends Activity {
    public static final String EXTRA_TASK_ID="cn.courseinbox.companion.TASK_ID";
    public static final String EXTRA_MESSAGE_ID="cn.courseinbox.companion.MESSAGE_ID";
    private static final int REQUEST_ALERT_PERMISSION=42;
    private static final int REQUEST_IMAGE_IMPORT=44;
    private static final long ALERT_RECONNECT_INTERVAL_MS=1000L;
    private MobileUi ui;private LinearLayout body;private ScrollView scroller;private String page="home",renderedPage="home";private int renderGeneration,messageOffset;
    private String pendingTaskId="",pendingMessageId="";private boolean showAdvancedSettings,alertReconnectPending;
    private boolean alertReconnectFeedback,alertSlowShown;
    private TextView listenerStateText;
    private AlertDialog listenerDiagnosticDialog;
    private int imageImportGeneration;
    private Uri recognizingImageUri,editingImageUri,restoringImageUri;
    private String imageImportKey,restoringImageText,restoringImageCourse,restoringImageTime;
    private boolean imageSavePending;
    private AlertDialog editingImageDialog,recognizingImageDialog;private EditText editingImageText,editingImageCourse,editingImageTime;
    private final Map<String,Integer> scrollPositions=new HashMap<>();
    private final Handler handler=new Handler();
    private final Runnable alertReconnectCheck=this::checkAlertConnection;
    private final Runnable refresh=new Runnable(){public void run(){CourseNotificationService.ensureConnected(MainActivity.this);render();handler.postDelayed(this,15000);}};
    private final Runnable foregroundListenerReset=()->{
        if(isFinishing()||isDestroyed()||Build.VERSION.SDK_INT<34||CourseNotificationService.isConnected()||!CourseNotificationService.hasAccess(this)
            ||NotificationQueue.preferences(this).getInt("listener_soft_reset_count",0)>0)return;
        if(ListenerRecoveryReceiver.armBindingResetFallback(this)&&CourseNotificationService.resetStaleBinding(this))render();
    };
    @Override public void onCreate(Bundle state){
        super.onCreate(state);ui=new MobileUi(this);
        getWindow().setStatusBarColor(MobileUi.BG);getWindow().setNavigationBarColor(MobileUi.BG);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if(state!=null)page=state.getString("page","home");openMessageIntent(getIntent());
        if(state!=null&&!state.getString("image_uri","").isEmpty()){
            Uri uri=Uri.parse(state.getString("image_uri"));
            imageImportKey=state.getString("image_import_key","image:"+UUID.randomUUID());
            if(state.getBoolean("image_recognize",false))handler.post(()->recognizeImage(uri));
            else{
                String text=state.getString("image_text",""),course=state.getString("image_course",""),time=state.getString("image_time","");
                setRestoringImage(uri,text,course,time);
                imageSavePending=state.getBoolean("image_save_pending",false);
                handler.post(()->{if(imageSavePending)resumeImageSave(uri,text,course,time);else restoreImageReview(uri,text,course,time);});
            }
        }
    }
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);openMessageIntent(intent);render();}
    private void openMessageIntent(Intent intent){String taskId=intent==null?null:intent.getStringExtra(EXTRA_TASK_ID);if(taskId!=null&&taskId.matches("[0-9a-f-]{36}")){pendingTaskId=taskId;page="tasks";}String id=intent==null?null:intent.getStringExtra(EXTRA_MESSAGE_ID);if(id!=null&&id.matches("[0-9a-f]{64}")){pendingMessageId=id;page="messages";scrollPositions.put("messages",0);}}
    private void render(){
        final int generation=++renderGeneration;
        listenerStateText=null;
        if(scroller!=null)scrollPositions.put(renderedPage,scroller.getScrollY());
        renderedPage=page;final int scrollY=scrollPositions.containsKey(page)?scrollPositions.get(page):0;
        LinearLayout root=ui.column();root.setBackgroundColor(MobileUi.BG);root.setFitsSystemWindows(true);
        ScrollView scroll=new ScrollView(this);scroller=scroll;body=ui.column();body.setPadding(ui.dp(18),ui.dp(14),ui.dp(18),ui.dp(20));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout nav=new LinearLayout(this);nav.setGravity(Gravity.CENTER);nav.setBackgroundColor(MobileUi.WHITE);nav.setPadding(ui.dp(10),ui.dp(7),ui.dp(10),ui.dp(7));
        String[] ids={"home","tasks","account"},names={"收件箱","任务","我的"};
        for(int i=0;i<ids.length;i++){final String id=ids[i];boolean selected=id.equals("home")?(page.equals("home")||page.equals("messages")):id.equals("tasks")?(page.equals("tasks")||page.equals("calendar")):page.equals("account");TextView item=ui.tab(names[i],selected,()->{page=id;render();});LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(0,-2,1);params.leftMargin=ui.dp(3);params.rightMargin=ui.dp(3);nav.addView(item,params);}
        root.addView(nav);setContentView(root);
        String title=page.equals("home")?"收件箱":page.equals("messages")?"全部消息":page.equals("tasks")?"任务":page.equals("calendar")?"截止日":"我的";
        LinearLayout heading=new LinearLayout(this);heading.setGravity(Gravity.CENTER_VERTICAL);TextView titleView=ui.text(title,26,MobileUi.INK,true);heading.addView(titleView,new LinearLayout.LayoutParams(0,-2,1));heading.addView(ui.smallAction("刷新",()->{if(page.equals("home")||page.equals("messages"))syncLearning();else{render();toast("正在刷新本机内容");}}));body.addView(heading);
        TextView loading=ui.text("正在载入…",14,MobileUi.MUTED,false);body.addView(loading);
        MobileStore.WORKER.execute(()->{
            try{LocalInbox inbox=MobileStore.get(this);List<LocalInbox.Message> messages=inbox.messages();List<LocalInbox.Task> tasks=inbox.tasks();LocalInbox.Message linkedMessage=inbox.sourceMessage(pendingMessageId);runOnUiThread(()->{if(generation!=renderGeneration||isFinishing())return;body.removeView(loading);if(page.equals("messages")&&!pendingMessageId.isEmpty())for(int i=0;i<messages.size();i++)if(messages.get(i).id.equals(pendingMessageId)){messageOffset=(i/100)*100;break;}switch(page){case "messages":messages(messages);break;case "tasks":tasks(tasks);break;case "calendar":calendar(tasks);break;case "account":account();break;default:home(messages,tasks);}if(page.equals("messages")&&!pendingMessageId.isEmpty()){String id=pendingMessageId;pendingMessageId="";if(linkedMessage!=null&&linkedMessage.id.equals(id))messageDetail(linkedMessage);}if(page.equals("tasks")&&!pendingTaskId.isEmpty()){String id=pendingTaskId;pendingTaskId="";for(LocalInbox.Task task:tasks)if(task.id.equals(id)){taskDetail(task);break;}}scroll.post(()->{if(generation==renderGeneration)scroll.scrollTo(0,scrollY);});});}
            catch(Exception error){runOnUiThread(()->{if(generation==renderGeneration)loading.setText("手机存档读取失败，请保留应用数据："+error.getMessage());});}
        });
    }
    private void home(List<LocalInbox.Message> messages,List<LocalInbox.Task> tasks){
        String loginState=learningState();LinearLayout welcome=ui.card(body);welcome.addView(ui.text("学习通 · "+loginState,17,MobileUi.INK,true));
        welcome.addView(ui.text(NotificationQueue.preferences(this).getString("learning_sync_status","尚无课程通知读取记录，点击同步获取。"),12,MobileUi.MUTED,false));
        ui.button(welcome,loginState.equals("已登录")?"同步学习通":"登录并同步学习通",true,this::syncLearning);
        LinearLayout totals=new LinearLayout(this);totals.setGravity(Gravity.CENTER_VERTICAL);totals.addView(ui.text(messages.size()+" 条消息",14,MobileUi.INK,true),new LinearLayout.LayoutParams(0,-2,1));totals.addView(ui.smallAction(tasks.stream().filter(t->t.status.equals("draft")).count()+" 项待确认",()->{page="tasks";render();}));welcome.addView(totals);
        LinearLayout section=new LinearLayout(this);section.setGravity(Gravity.CENTER_VERTICAL);section.addView(ui.text("最近任务与消息",17,MobileUi.INK,true),new LinearLayout.LayoutParams(0,-2,1));section.addView(ui.smallAction("全部消息",()->{page="messages";render();}));body.addView(section);
        if(messages.isEmpty()){empty("暂时没有消息。点击同步读取课程通知；聊天消息可从“我的”打开。");return;}
        for(LocalInbox.Message message:messages.subList(0,Math.min(3,messages.size()))){LinearLayout card=messageCard(body,message,120);for(LocalInbox.Task task:tasks)if(task.messageId.equals(message.id)&&!task.status.equals("ignored")){card.addView(ui.text("任务 · "+MobileTaskRules.statusLabel(task.status)+(task.deadline.isEmpty()?" · 未明确截止":""),12,MobileUi.GREEN,true));ui.button(card,task.status.equals("draft")?"核对任务":"查看任务",false,()->taskDetail(task));break;}}
    }
    private void messages(List<LocalInbox.Message> values){
        LinearLayout actions=new LinearLayout(this);actions.setGravity(Gravity.RIGHT);actions.addView(ui.smallAction("导入文字",this::manualImport));actions.addView(ui.smallAction("识别图片",this::pickImage));if(!values.isEmpty())actions.addView(ui.smallAction("清理",()->chooseMessageCleanup(values)));body.addView(actions);
        if(values.isEmpty()){empty("还没有消息。打开学习通查看课程或聊天。");return;}
        messageOffset=Math.min(messageOffset,((values.size()-1)/100)*100);int end=Math.min(messageOffset+100,values.size());
        body.addView(ui.text("共 "+values.size()+" 条 · 显示 "+(messageOffset+1)+"–"+end,12,MobileUi.MUTED,false));
        if(messageOffset>0)ui.button(body,"查看较新的 100 条",false,()->changeMessagePage(-100));
        for(LocalInbox.Message message:values.subList(messageOffset,end))messageCard(body,message,180);
        if(end<values.size())ui.button(body,"查看更早的 100 条",false,()->changeMessagePage(100));
    }
    private LinearLayout messageCard(LinearLayout parent,LocalInbox.Message message,int previewLength){
        LinearLayout card=ui.card(parent);TextView title=ui.text(message.title.isEmpty()?message.conversation:message.title,16,MobileUi.INK,true);title.setMaxLines(1);title.setEllipsize(TextUtils.TruncateAt.END);card.addView(title);
        card.addView(ui.text(message.source+" · "+(message.timeKnown&&message.capturedAt>0?"发布："+date(message.capturedAt):"接收："+date(message.receivedAt)),12,MobileUi.MUTED,false));String preview=message.text.length()>previewLength?message.text.substring(0,previewLength)+"…":message.text;TextView previewText=ui.text(preview,14,MobileUi.INK,false);previewText.setMaxLines(previewLength<=120?2:3);previewText.setEllipsize(TextUtils.TruncateAt.END);card.addView(previewText);card.addView(ui.text("打开原文  ›",12,MobileUi.GREEN,true));card.setOnClickListener(v->messageDetail(message));return card;
    }
    private void chooseMessageCleanup(List<LocalInbox.Message> values){
        List<LocalInbox.Message> snapshot=new ArrayList<>(values),shown=new ArrayList<>(snapshot.subList(messageOffset,Math.min(messageOffset+100,snapshot.size())));Set<String> selected=new HashSet<>();String[] labels=new String[shown.size()];
        for(int i=0;i<shown.size();i++){LocalInbox.Message message=shown.get(i);labels[i]=(message.title.isEmpty()?message.conversation:message.title)+"\n"+date(message.timeKnown&&message.capturedAt>0?message.capturedAt:message.receivedAt);}
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("选择当前页消息").setMultiChoiceItems(labels,null,(d,index,checked)->{if(checked)selected.add(shown.get(index).id);else selected.remove(shown.get(index).id);}).setNegativeButton("取消",null).setNeutralButton("清空全部",(d,w)->{Set<String> all=new HashSet<>();for(LocalInbox.Message message:snapshot)all.add(message.id);confirmMessageCleanup(all);}).setPositiveButton("清理所选",null).create();
        dialog.show();dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{if(selected.isEmpty()){toast("请先选择消息");return;}dialog.dismiss();confirmMessageCleanup(selected);});
    }
    private void confirmMessageCleanup(Collection<String> selected){
        Set<String> ids=new HashSet<>(selected);
        new AlertDialog.Builder(this).setTitle("清理 "+ids.size()+" 条消息？").setMessage("这些消息将从收件箱移除。已有任务及其引用原文会保留；未被任务引用的原文将删除。").setNegativeButton("取消",null).setPositiveButton("清理",(d,w)->MobileStore.WORKER.execute(()->{
            try{int removed=MobileStore.get(this).clearMessages(ids);runOnUiThread(()->{if(isFinishing()||isDestroyed())return;messageOffset=0;scrollPositions.put("messages",0);render();toast("已清理 "+removed+" 条消息");});}
            catch(Exception error){runOnUiThread(()->{if(isFinishing()||isDestroyed())return;render();toast("清理未全部完成："+error.getMessage());});}
        })).show();
    }
    private void changeMessagePage(int step){messageOffset+=step;if(scroller!=null)scroller.scrollTo(0,0);scrollPositions.put("messages",0);render();}
    private void messageDetail(LocalInbox.Message message){String value="来源："+message.source+"\n会话："+message.conversation+"\n发送者："+message.sender+"\n发布时间："+(message.timeKnown?date(message.capturedAt):"未知")+"\n接收时间："+date(message.receivedAt)+"\n\n"+message.text;TextView text=ui.text(value,15,MobileUi.INK,false);text.setTextIsSelectable(true);text.setPadding(ui.dp(20),ui.dp(10),ui.dp(20),ui.dp(10));ScrollView scroll=new ScrollView(this);scroll.addView(text);AlertDialog.Builder dialog=new AlertDialog.Builder(this).setTitle("消息原文").setView(scroll).setPositiveButton("关闭",null);File image=ImageEvidenceStore.resolve(getFilesDir(),message.url);if(image!=null)dialog.setNeutralButton("查看原图",(d,w)->viewOriginalImage(image));else if(LearningUrls.allowed(message.url))dialog.setNeutralButton("打开来源",(d,w)->openLearning(message.url));dialog.show();}
    private void tasks(List<LocalInbox.Task> values){
        taskModeTabs();
        List<LocalInbox.Task> sorted=new ArrayList<>(values);sorted.sort(Comparator.comparing((LocalInbox.Task t)->!t.status.equals("draft")).thenComparing(t->t.deadline.isEmpty()?"9999":t.deadline));
        boolean any=false;
        for(LocalInbox.Task task:sorted){if(task.status.equals("ignored"))continue;any=true;taskCard(task);}
        if(!any)empty("还没有任务。收到结构明确的作业、考试或阅读通知后，会先生成待确认草稿。");
    }
    private void taskCard(LocalInbox.Task task){LinearLayout card=ui.card(body);boolean overdue=MobileTaskRules.overdue(task.deadline,task.status,System.currentTimeMillis());TextView title=ui.text(task.title,18,MobileUi.INK,true);title.setMaxLines(2);title.setEllipsize(TextUtils.TruncateAt.END);card.addView(title);card.addView(ui.text(task.course+(task.course.isEmpty()?"":" · ")+MobileTaskRules.displayStatus(task.deadline,task.status,System.currentTimeMillis()),13,overdue?MobileUi.RED:MobileUi.GREEN,true));card.addView(ui.text("截止："+(task.deadline.isEmpty()?"未明确":task.deadline),13,overdue?MobileUi.RED:MobileUi.MUTED,false));ui.button(card,task.status.equals("draft")?"核对任务":"记录状态",task.status.equals("draft"),()->taskDetail(task));}
    private void taskModeTabs(){LinearLayout modes=new LinearLayout(this);modes.setPadding(0,ui.dp(4),0,0);TextView list=ui.tab("清单",page.equals("tasks"),()->{page="tasks";render();});TextView calendar=ui.tab("日历",page.equals("calendar"),()->{page="calendar";render();});modes.addView(list,new LinearLayout.LayoutParams(0,-2,1));LinearLayout.LayoutParams second=new LinearLayout.LayoutParams(0,-2,1);second.leftMargin=ui.dp(8);modes.addView(calendar,second);body.addView(modes);}
    private void taskDetail(LocalInbox.Task task){
        if(task.status.equals("draft")){
            LinearLayout form=ui.column();form.setPadding(ui.dp(20),0,ui.dp(20),ui.dp(12));EditText title=ui.input(form,"任务名称",task.title),course=ui.input(form,"课程",task.course),deadline=ui.input(form,"截止（日期或 YYYY-MM-DD HH:mm，可留空）",task.deadline);if(!task.warning.isEmpty())form.addView(ui.text(task.warning,13,MobileUi.MUTED,false));form.addView(ui.text(task.requirements,14,MobileUi.INK,false));ScrollView scroll=new ScrollView(this);scroll.addView(form);
            AlertDialog dialog=new AlertDialog.Builder(this).setTitle("核对任务与原文").setView(scroll).setNegativeButton("取消",null).setNeutralButton("忽略",(d,w)->mutate(()->MobileStore.get(this).setStatus(task.id,"ignored"))).setPositiveButton("确认",null).create();dialog.show();dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{String due=deadline.getText().toString().trim();if(due.matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}"))due=due.replace(' ','T')+":00+08:00";if(!MobileTaskRules.validDeadline(due)){deadline.setError("请填写有效日期或完整时间");return;}final String value=due,name=title.getText().toString().trim(),subject=course.getText().toString().trim();if(name.isEmpty()||name.length()>100){title.setError("任务名称应为 1–100 字");return;}if(subject.length()>100){course.setError("课程名称不能超过 100 字");return;}mutate(()->MobileStore.get(this).confirm(task.id,name,subject,value));dialog.dismiss();});
        }else{
            String[] codes={"pending","in_progress","done","submitted","cancelled"},labels={"待开始","进行中","已做完","已提交","已取消"};int current=Arrays.asList(codes).indexOf(task.status);
            new AlertDialog.Builder(this).setTitle(task.title).setMessage("状态由你手动记录，“已提交”不代表学习通平台回执。\n\n"+task.requirements).setPositiveButton("查看来源",(d,w)->showTaskSource(task)).setNeutralButton("修改状态",(d,w)->new AlertDialog.Builder(this).setTitle("记录任务状态").setSingleChoiceItems(labels,current,(dialog,index)->{mutate(()->MobileStore.get(this).setStatus(task.id,codes[index]));dialog.dismiss();}).setNegativeButton("取消",null).show()).setNegativeButton("修改截止",(d,w)->editDeadline(task)).show();
        }
    }
    private void editDeadline(LocalInbox.Task task){
        LinearLayout form=ui.column();form.setPadding(ui.dp(20),0,ui.dp(20),ui.dp(10));
        EditText input=ui.input(form,"截止（YYYY-MM-DD 或 YYYY-MM-DD HH:mm，可留空）",task.deadline);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("修改截止时间").setView(form).setNegativeButton("取消",null).setPositiveButton("保存",null).create();dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{String due=input.getText().toString().trim();if(due.matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}"))due=due.replace(' ','T')+":00+08:00";if(!MobileTaskRules.validDeadline(due)){input.setError("请填写有效日期或完整时间");return;}final String value=due;mutate(()->MobileStore.get(this).updateDeadline(task.id,value));dialog.dismiss();});
    }
    private void configureDeadlineAlerts(){
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},43);return;}
        if(!DeadlineReminder.canShow(this)){startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,getPackageName()));return;}
        DeadlineReminder.refresh(this);toast("截止提醒已开启。只有日期的任务于前一天和当天上午 9 点提醒，具体截止时刻仍需核对。");
    }
    private void showTaskSource(LocalInbox.Task task){MobileStore.WORKER.execute(()->{try{LocalInbox.Message message=MobileStore.get(this).sourceMessage(task.messageId);if(message!=null)runOnUiThread(()->messageDetail(message));else runOnUiThread(()->toast("未找到任务原文"));}catch(Exception e){runOnUiThread(()->toast(e.getMessage()));}});}
    private void calendar(List<LocalInbox.Task> tasks){
        taskModeTabs();
        List<LocalInbox.Task> dates=new ArrayList<>();for(LocalInbox.Task t:tasks)if(!t.deadline.isEmpty()&&!Arrays.asList("draft","ignored","cancelled").contains(t.status))dates.add(t);dates.sort(Comparator.comparing(t->t.deadline));
        List<LocalInbox.Task> undated=new ArrayList<>();for(LocalInbox.Task task:tasks)if(task.deadline.isEmpty()&&!Arrays.asList("ignored","cancelled").contains(task.status))undated.add(task);
        if(dates.isEmpty()&&undated.isEmpty()){empty("还没有已确认且带截止日期的任务。");return;}
        String group="";for(LocalInbox.Task task:dates){String day=task.deadline.substring(0,10);if(!day.equals(group)){group=day;body.addView(ui.text(day,18,MobileUi.INK,true));}LinearLayout card=ui.card(body);boolean overdue=MobileTaskRules.overdue(task.deadline,task.status,System.currentTimeMillis());card.addView(ui.text(task.title,17,overdue?MobileUi.RED:MobileUi.INK,true));card.addView(ui.text(MobileTaskRules.displayStatus(task.deadline,task.status,System.currentTimeMillis())+" · "+task.deadline,13,overdue?MobileUi.RED:MobileUi.MUTED,false));ui.button(card,"查看任务",false,()->taskDetail(task));}
        if(!undated.isEmpty()){body.addView(ui.text("未明确截止",18,MobileUi.INK,true));for(LocalInbox.Task task:undated)taskCard(task);}
    }
    private void account(){
        LinearLayout computerReminders=ui.card(body);computerReminders.addView(ui.text("电脑 → 手机提醒",16,MobileUi.INK,true));computerReminders.addView(ui.text("电脑后台采集学习通，同一 Wi-Fi 下在手机接收提醒。",13,MobileUi.MUTED,false));ui.button(computerReminders,"接收电脑提醒",true,()->startActivity(new Intent(this,ComputerRemindersActivity.class)));
        String loginState=learningState();LinearLayout learning=ui.card(body);learning.addView(ui.text("学习通",13,MobileUi.MUTED,true));learning.addView(ui.text(loginState,19,MobileUi.INK,true));ui.button(learning,loginState.equals("已登录")?"打开学习通":"登录学习通",true,()->openLearning(LearningUrls.PORTAL));
        LinearLayout sources=new LinearLayout(this);TextView chat=ui.smallAction("聊天消息",()->openLearning(LearningUrls.CHAT));TextView notices=ui.smallAction("课程通知",()->openLearning(LearningUrls.NOTICES));sources.addView(chat,new LinearLayout.LayoutParams(0,-2,1));LinearLayout.LayoutParams noticesParams=new LinearLayout.LayoutParams(0,-2,1);noticesParams.leftMargin=ui.dp(8);sources.addView(notices,noticesParams);learning.addView(sources);
        LinearLayout permission=ui.card(body);permission.addView(ui.text("手机提醒",16,MobileUi.INK,true));listenerStateText=ui.text(notificationState(),14,CourseNotificationService.isConnected()?MobileUi.GREEN:MobileUi.MUTED,false);permission.addView(listenerStateText);if(!CourseNotificationService.hasAccess(this))permission.addView(ui.text("开启后可保存学习通发布到通知栏的消息。",13,MobileUi.MUTED,false));else if(!CourseNotificationService.isConnected()){permission.addView(ui.text("系统已授权，正在等待 Android 连接。连接后会自动补收当前通知栏。",13,MobileUi.MUTED,false));android.content.SharedPreferences prefs=NotificationQueue.preferences(this);String diagnostic=prefs.getString("listener_status","");if(!diagnostic.isEmpty())permission.addView(ui.text(diagnostic,12,MobileUi.MUTED,false));int attempts=prefs.getInt("listener_rebind_count",0);if(attempts>0)permission.addView(ui.text("已向系统请求连接 "+attempts+" 次，尚未收到连接回调。",12,MobileUi.MUTED,false));if(prefs.getInt("listener_soft_reset_count",0)>0)permission.addView(ui.text("已尝试重建接收服务绑定 1 次，未改动系统授权。",12,MobileUi.MUTED,false));}
        ui.button(permission,!CourseNotificationService.isConnected()&&CourseNotificationService.hasAccess(this)?"查看连接进度":MobileAlert.canShow(this)?"管理提醒设置":"开启提醒",false,this::configureAlerts);permission.addView(ui.smallAction("连接诊断",this::showListenerDiagnostics));captureStatus(permission);
        LinearLayout deadlines=ui.card(body);deadlines.addView(ui.text("任务截止提醒",16,MobileUi.INK,true));
        Switch toggle=new Switch(this);toggle.setText("提醒本机已确认任务");toggle.setChecked(DeadlineReminder.enabled(this));deadlines.addView(toggle);
        toggle.setOnCheckedChangeListener((button,enabled)->{DeadlineReminder.setEnabled(this,enabled);if(enabled)configureDeadlineAlerts();});
        deadlines.addView(ui.text(DeadlineReminder.status(this),13,MobileUi.MUTED,false));
        deadlines.addView(ui.text("只有日期：前一天和当天上午 9 点提醒；不依赖电脑或通知读取权限。",12,MobileUi.MUTED,false));
        if(!DeadlineReminder.canShow(this))ui.button(deadlines,"允许截止通知",false,this::configureDeadlineAlerts);
        body.addView(ui.smallAction(showAdvancedSettings?"收起更多设置":"更多设置",()->{showAdvancedSettings=!showAdvancedSettings;render();}));
        if(showAdvancedSettings){
            LinearLayout advanced=ui.card(body);ui.button(advanced,"补收当前通知栏",false,()->{CourseNotificationService.ensureConnected(this);String result=CourseNotificationService.inspectVisibleNotifications(this);toast(result);handler.postDelayed(this::render,1000);});
            ui.button(advanced,"连接电脑",false,()->startActivity(new Intent(this,ComputerActivity.class)));
            ui.button(advanced,"退出学习通账号",false,()->new AlertDialog.Builder(this).setTitle("退出账号？").setMessage("清除本应用内的学习通登录会话，消息与任务保留。系统通知权限仍可在 Android 设置中管理。").setNegativeButton("取消",null).setPositiveButton("退出",(d,w)->{CookieManager.getInstance().removeAllCookies(done->{WebStorage.getInstance().deleteAllData();NotificationQueue.preferences(this).edit().putString("learning_state","idle").apply();MobileStore.WORKER.execute(()->CookieManager.getInstance().flush());render();});}).show());
            advanced.addView(ui.text("网页消息在学习通页面打开时读取；后台仅接收学习通实际发布到通知栏的内容。",12,MobileUi.MUTED,false));
        }
    }
    private void captureStatus(LinearLayout parent){android.content.SharedPreferences prefs=NotificationQueue.preferences(this);String status=prefs.getString("local_capture_status","");int count=prefs.getInt("local_pending_count",0);boolean failed=status.contains("失败");if(failed)parent.addView(ui.text(status,12,MobileUi.RED,false));if(count>0||failed){if(count>0)parent.addView(ui.text(count+" 条原文待保存",13,MobileUi.RED,true));ui.button(parent,"重试保存",false,()->{MobileStore.retryNotifications(this);toast("正在重试保存。");handler.postDelayed(this::render,1000);});}}
    private void configureAlerts(){
        if(!CourseNotificationService.hasAccess(this)){openListenerSettings();return;}
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},REQUEST_ALERT_PERMISSION);return;}
        if(!MobileAlert.canShow(this)){startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,getPackageName()));return;}
        if(CourseNotificationService.isConnected()){toast("手机提醒已开启，收到学习通系统通知后会显示 CampusInbox 提醒。");return;}
        if(alertReconnectPending){alertReconnectFeedback=true;if(ListenerDiagnostics.shouldOfferHelp(this))showListenerDiagnostics();else toast(notificationState()+"，连接后会自动更新。");return;}
        ListenerRecoveryReceiver.begin(this);
        toast("正在等待系统连接，可继续使用应用，状态会自动更新。");
        watchAlertConnection(true);
    }
    private void watchAlertConnection(boolean feedback){
        alertReconnectFeedback|=feedback;
        if(alertReconnectPending)return;
        alertReconnectPending=true;alertSlowShown=false;handler.post(alertReconnectCheck);
    }
    private void checkAlertConnection(){
        if(!alertReconnectPending||isFinishing()||isDestroyed())return;
        if(CourseNotificationService.isConnected()||!CourseNotificationService.hasAccess(this)){
            boolean notify=alertReconnectFeedback&&CourseNotificationService.isConnected();
            alertReconnectPending=false;alertReconnectFeedback=false;
            if(CourseNotificationService.isConnected()&&listenerDiagnosticDialog!=null)listenerDiagnosticDialog.dismiss();
            if(notify)toast("手机提醒已连接，当前通知栏会自动补收。");
            render();return;
        }
        if(listenerStateText!=null)listenerStateText.setText(notificationState());
        if(alertReconnectFeedback&&!alertSlowShown&&ListenerDiagnostics.shouldOfferHelp(this)){
            alertSlowShown=true;toast("系统连接仍较慢，当前尚不能接收通知。可在“我的 → 连接诊断”查看详情。");
        }
        handler.postDelayed(alertReconnectCheck,ALERT_RECONNECT_INTERVAL_MS);
    }
    private void showListenerDiagnostics(){
        if(listenerDiagnosticDialog!=null)return;
        String version="未知";try{version=getPackageManager().getPackageInfo(getPackageName(),0).versionName;}catch(PackageManager.NameNotFoundException ignored){}
        final String report="CampusInbox "+version+"\n设备："+Build.MANUFACTURER+" "+Build.MODEL+"\nAndroid "+Build.VERSION.RELEASE+"（API "+Build.VERSION.SDK_INT+"）\n"+ListenerDiagnostics.report(this);
        TextView details=ui.text(report,12,MobileUi.INK,false);details.setTextIsSelectable(true);details.setPadding(ui.dp(20),ui.dp(12),ui.dp(20),ui.dp(12));ScrollView scroll=new ScrollView(this);scroll.addView(details);
        listenerDiagnosticDialog=new AlertDialog.Builder(this).setTitle("通知连接诊断").setView(scroll)
            .setPositiveButton("复制诊断",(dialog,which)->{android.content.ClipboardManager clipboard=(android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE);if(clipboard!=null){clipboard.setPrimaryClip(android.content.ClipData.newPlainText("CampusInbox 通知连接诊断",report));toast("连接诊断已复制，可粘贴反馈。");}})
            .setNeutralButton("通知使用权",(dialog,which)->openListenerSettings()).setNegativeButton("关闭",null)
            .setOnDismissListener(dialog->listenerDiagnosticDialog=null).show();
    }
    private void openListenerSettings(){
        if(Build.VERSION.SDK_INT>=30)try{startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS).putExtra(Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME,new android.content.ComponentName(this,CourseNotificationService.class).flattenToString()));return;}catch(android.content.ActivityNotFoundException|SecurityException ignored){}
        try{startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));}catch(android.content.ActivityNotFoundException|SecurityException error){toast("无法打开系统通知使用权，请从手机设置进入。");}
    }
    private String notificationState(){return ListenerDiagnostics.status(this);}
    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] results){
        super.onRequestPermissionsResult(requestCode,permissions,results);
        if(requestCode==43){DeadlineReminder.refresh(this);render();return;}
        if(requestCode!=REQUEST_ALERT_PERMISSION)return;
        if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED)configureAlerts();
        else toast("CampusInbox 提醒未授权；仍可保存学习通通知原文。");
        render();
    }
    private String learningState(){String state=NotificationQueue.preferences(this).getString("learning_state","idle");switch(state){case "connected":return "已登录";case "waiting_scan":return "等待扫码确认";case "expired":return "登录已过期";case "partial":return "网页消息待重试";case "error":return "连接异常";default:return "未登录";}}
    private void pickImage(){
        if(imageSavePending||restoringImageUri!=null||recognizingImageUri!=null||editingImageDialog!=null){toast("请先完成当前图片导入。");return;}
        Intent select=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*");
        startActivityForResult(select,REQUEST_IMAGE_IMPORT);
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        super.onActivityResult(requestCode,resultCode,data);
        if(requestCode==REQUEST_IMAGE_IMPORT&&resultCode==RESULT_OK&&data!=null&&data.getData()!=null){
            Uri uri=data.getData();
            try{getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){/* The immediate picker grant is still usable. */}
            imageImportKey="image:"+UUID.randomUUID();
            recognizeImage(uri);
        }
    }
    private void recognizeImage(Uri uri){
        final int generation=++imageImportGeneration;
        recognizingImageUri=uri;
        AlertDialog progress=new AlertDialog.Builder(this).setTitle("识别图片").setMessage("正在本机识别图片中的文字…")
            .setNegativeButton("取消",(d,w)->{imageImportGeneration++;recognizingImageUri=null;releaseImageUri(uri);}).create();
        recognizingImageDialog=progress;
        progress.setOnDismissListener(d->{if(recognizingImageDialog==progress)recognizingImageDialog=null;});
        progress.setOnCancelListener(d->{imageImportGeneration++;recognizingImageUri=null;releaseImageUri(uri);});progress.show();
        MobileImageOcr.WORKER.execute(()->{
            try{
                MobileImageOcr.Selection selection=MobileImageOcr.open(this,uri);
                runOnUiThread(()->{
                    if(generation!=imageImportGeneration||isFinishing()||isDestroyed()){selection.bitmap.recycle();return;}
                    try{
                        TextRecognizer recognizer=TextRecognition.getClient(new ChineseTextRecognizerOptions.Builder().build());
                        recognizer.process(InputImage.fromBitmap(selection.bitmap,0))
                            .addOnSuccessListener(result->{
                                progress.dismiss();
                                if(generation!=imageImportGeneration||isFinishing()||isDestroyed()){selection.bitmap.recycle();return;}
                                recognizingImageUri=null;
                                try{String raw=result.getText();reviewImage(selection,raw==null||raw.trim().isEmpty()?"":ImageImportPolicy.reviewText(raw),"","",uri);}
                                catch(IllegalArgumentException error){selection.bitmap.recycle();releaseImageUri(uri);toast(error.getMessage());}
                            })
                            .addOnFailureListener(error->{progress.dismiss();selection.bitmap.recycle();if(generation==imageImportGeneration){recognizingImageUri=null;releaseImageUri(uri);toast("图片文字识别失败，请换一张清晰截图。");}})
                            .addOnCompleteListener(task->recognizer.close());
                    }catch(RuntimeException error){progress.dismiss();selection.bitmap.recycle();recognizingImageUri=null;releaseImageUri(uri);toast("本机图片识别无法启动："+error.getMessage());}
                });
            }catch(Exception error){runOnUiThread(()->{progress.dismiss();if(generation==imageImportGeneration&&!isFinishing()){recognizingImageUri=null;releaseImageUri(uri);toast(error.getMessage());}});}
        });
    }
    private void setRestoringImage(Uri uri,String recognized,String subject,String posted){
        restoringImageUri=uri;restoringImageText=recognized;restoringImageCourse=subject;restoringImageTime=posted;
    }
    private void clearRestoringImage(){restoringImageUri=null;restoringImageText=null;restoringImageCourse=null;restoringImageTime=null;}
    private void resumeImageSave(Uri uri,String recognized,String subject,String posted){
        // The same serial worker handles saving. This check runs after the previous Activity's write.
        final String importKey=imageImportKey;
        MobileStore.WORKER.execute(()->{
            try{
                LocalInbox inbox=MobileStore.get(this);
                String id=new LocalInbox.Message(importKey,"手机图片导入","",subject,"","图片原文",recognized,0,false,"").id;
                boolean saved=false,draft=false;
                saved=inbox.sourceMessage(id)!=null;
                if(saved)for(LocalInbox.Task task:inbox.tasks())if(task.messageId.equals(id)){draft=true;break;}
                final boolean found=saved,hasDraft=draft;
                runOnUiThread(()->{
                    if(isFinishing()||isDestroyed())return;
                    imageSavePending=false;
                    if(found){clearRestoringImage();releaseImageUri(uri);page=hasDraft?"tasks":"messages";render();toast("图片文字已保存。");}
                    else restoreImageReview(uri,recognized,subject,posted);
                });
            }catch(Exception error){runOnUiThread(()->{if(isFinishing()||isDestroyed())return;imageSavePending=false;restoreImageReview(uri,recognized,subject,posted);});}
        });
    }
    private void restoreImageReview(Uri uri,String recognized,String subject,String posted){
        setRestoringImage(uri,recognized,subject,posted);
        MobileImageOcr.WORKER.execute(()->{
            try{MobileImageOcr.Selection selection=MobileImageOcr.open(this,uri);runOnUiThread(()->{if(isFinishing()||isDestroyed()){selection.bitmap.recycle();return;}reviewImage(selection,recognized,subject,posted,uri);});}
            catch(Exception error){runOnUiThread(()->{if(isFinishing()||isDestroyed())return;clearRestoringImage();releaseImageUri(uri);toast("图片校对无法恢复："+error.getMessage());});}
        });
    }
    private void releaseImageUri(Uri uri){try{getContentResolver().releasePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){}}
    private void reviewImage(MobileImageOcr.Selection selection,String recognized,String initialCourse,String initialTime,Uri uri){
        LinearLayout form=ui.column();form.setPadding(ui.dp(20),0,ui.dp(20),ui.dp(12));
        ImageView preview=new ImageView(this);preview.setImageBitmap(selection.bitmap);preview.setAdjustViewBounds(true);preview.setMaxHeight(ui.dp(220));form.addView(preview,new LinearLayout.LayoutParams(-1,-2));
        form.addView(ui.text(recognized.isEmpty()?"未识别到文字，可对照原图手动填写；相对日期需要消息原发布时间。":"请核对识别文字；相对日期需要填写消息原发布时间。",13,MobileUi.MUTED,false));
        EditText input=ui.input(form,"识别文字（可修改）",recognized);input.setMinLines(5);input.setGravity(Gravity.TOP);
        EditText course=ui.input(form,"课程（可选）",initialCourse),time=ui.input(form,"消息发布时间（YYYY-MM-DD HH:mm，可留空）",initialTime);
        ScrollView scroll=new ScrollView(this);scroll.addView(form);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("核对图片文字").setView(scroll).setNegativeButton("取消",null).setPositiveButton("保存并生成草稿",null).create();
        clearRestoringImage();editingImageUri=uri;editingImageDialog=dialog;editingImageText=input;editingImageCourse=course;editingImageTime=time;
        dialog.setOnDismissListener(d->{selection.bitmap.recycle();if(editingImageDialog==dialog){editingImageDialog=null;editingImageUri=null;editingImageText=null;editingImageCourse=null;editingImageTime=null;}if(!isChangingConfigurations())releaseImageUri(uri);});dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            final String text;final long posted;
            try{text=ImageImportPolicy.validateEditedText(input.getText().toString());}
            catch(IllegalArgumentException error){input.setError(error.getMessage());return;}
            try{String value=time.getText().toString().trim();posted=value.isEmpty()?0:LocalDateTime.parse(value,DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm").withResolverStyle(java.time.format.ResolverStyle.STRICT)).atOffset(ZoneOffset.ofHours(8)).toInstant().toEpochMilli();}
            catch(RuntimeException error){time.setError("消息发布时间无效");return;}
            final String subject=course.getText().toString().trim();if(subject.length()>100){course.setError("课程名称不能超过 100 字");return;}
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setText("保存中…");
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(false);
            dialog.setCancelable(false);
            input.setEnabled(false);course.setEnabled(false);time.setEnabled(false);
            imageSavePending=true;
            final String importKey=imageImportKey;
            MobileStore.WORKER.execute(()->{
                String reference=null;
                try{
                    reference=ImageEvidenceStore.save(getFilesDir(),selection.bytes);
                    LocalInbox inbox=MobileStore.get(this);int before=inbox.tasks().size();
                    boolean saved=inbox.ingest(new LocalInbox.Message(importKey,"手机图片导入","",subject,"","图片原文",text,posted,posted>0,reference));
                    if(!saved){ImageEvidenceStore.remove(getFilesDir(),reference);reference=null;}
                    boolean draft=inbox.tasks().size()>before;
                    runOnUiThread(()->{if(isFinishing()||isDestroyed())return;imageSavePending=false;dialog.dismiss();page=draft?"tasks":"messages";render();toast(draft?"图片文字已保存，请核对任务草稿。":"图片文字已保存，未识别出任务；可在消息中查看。");});
                }catch(Exception error){
                    if(reference!=null)try{ImageEvidenceStore.remove(getFilesDir(),reference);}catch(Exception ignored){}
                    runOnUiThread(()->{if(isFinishing()||isDestroyed())return;imageSavePending=false;if(dialog.isShowing()){dialog.setCancelable(true);dialog.getButton(AlertDialog.BUTTON_POSITIVE).setText("保存并生成草稿");dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(true);input.setEnabled(true);course.setEnabled(true);time.setEnabled(true);}toast("图片保存失败："+error.getMessage());});
                }
            });
        });
    }
    private void viewOriginalImage(File image){
        MobileImageOcr.WORKER.execute(()->{
            try{Bitmap bitmap=MobileImageOcr.preview(image);runOnUiThread(()->{
                if(isFinishing()||isDestroyed()){bitmap.recycle();return;}
                ImageView view=new ImageView(this);view.setImageBitmap(bitmap);view.setAdjustViewBounds(true);view.setPadding(ui.dp(12),ui.dp(12),ui.dp(12),ui.dp(12));
                ScrollView scroll=new ScrollView(this);scroll.addView(view);
                AlertDialog dialog=new AlertDialog.Builder(this).setTitle("导入的原图").setView(scroll).setPositiveButton("关闭",null).create();
                dialog.setOnDismissListener(d->bitmap.recycle());dialog.show();
            });}catch(Exception error){runOnUiThread(()->toast("原图无法打开："+error.getMessage()));}
        });
    }
    private void manualImport(){LinearLayout form=ui.column();form.setPadding(ui.dp(20),0,ui.dp(20),ui.dp(12));EditText course=ui.input(form,"课程（可选）",""),input=ui.input(form,"通知原文","");input.setMinLines(5);input.setGravity(Gravity.TOP);EditText time=ui.input(form,"消息发布时间（YYYY-MM-DD HH:mm，可留空）","");ScrollView scroll=new ScrollView(this);scroll.addView(form);new AlertDialog.Builder(this).setTitle("导入文字通知").setView(scroll).setNegativeButton("取消",null).setPositiveButton("保存",(d,w)->{long at=0;try{String value=time.getText().toString().trim();if(!value.isEmpty())at=LocalDateTime.parse(value,DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm").withResolverStyle(java.time.format.ResolverStyle.STRICT)).atOffset(ZoneOffset.ofHours(8)).toInstant().toEpochMilli();}catch(Exception error){toast("发布时间无效，本次未保存");return;}final long posted=at;final String text=input.getText().toString(),subject=course.getText().toString();mutate(()->MobileStore.get(this).ingest(new LocalInbox.Message("manual:"+UUID.randomUUID(),"手动导入","",subject,"","手动导入",text,posted,posted>0,"")));}).show();}
    private interface Change{void apply()throws Exception;}
    private void mutate(Change action){MobileStore.WORKER.execute(()->{try{action.apply();DeadlineReminder.refresh(this);runOnUiThread(this::render);}catch(Exception error){runOnUiThread(()->toast(error.getMessage()));}});}
    private void openLearning(String url){startActivity(new Intent(this,LearningLoginActivity.class).putExtra("url",url));}
    private void syncLearning(){NotificationQueue.preferences(this).edit().putString("learning_sync_status","正在打开课程通知…").apply();startActivity(new Intent(this,LearningLoginActivity.class).putExtra("url",LearningUrls.NOTICES).putExtra("return_after_read",true));}
    private void empty(String text){LinearLayout card=ui.card(body);card.addView(ui.text(text,15,MobileUi.MUTED,false));}
    private void toast(String text){Toast.makeText(this,text,Toast.LENGTH_LONG).show();}
    private String date(long at){return Instant.ofEpochMilli(at).atOffset(ZoneOffset.ofHours(8)).format(DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm"));}
    @Override protected void onResume(){super.onResume();ListenerRecoveryReceiver.begin(this);MobileStore.retryNotifications(this);DeadlineReminder.refresh(this);render();if(CourseNotificationService.hasAccess(this)&&!CourseNotificationService.isConnected())watchAlertConnection(false);handler.removeCallbacks(refresh);handler.removeCallbacks(foregroundListenerReset);handler.postDelayed(refresh,15000);handler.postDelayed(foregroundListenerReset,15000);}
    @Override protected void onPause(){super.onPause();handler.removeCallbacks(refresh);handler.removeCallbacks(foregroundListenerReset);handler.removeCallbacks(alertReconnectCheck);alertReconnectPending=false;alertReconnectFeedback=false;if(listenerDiagnosticDialog!=null)listenerDiagnosticDialog.dismiss();}
    @Override protected void onSaveInstanceState(Bundle state){
        super.onSaveInstanceState(state);state.putString("page",page);
        if(editingImageDialog!=null&&editingImageDialog.isShowing()&&editingImageUri!=null){
            state.putString("image_uri",editingImageUri.toString());
            String imageText=editingImageText.getText().toString();
            state.putString("image_text",imageSavePending?imageText.trim():imageText);
            state.putString("image_course",editingImageCourse.getText().toString());
            state.putString("image_time",editingImageTime.getText().toString());
            state.putBoolean("image_save_pending",imageSavePending);
        }else if(restoringImageUri!=null){
            state.putString("image_uri",restoringImageUri.toString());
            state.putString("image_text",restoringImageText);
            state.putString("image_course",restoringImageCourse);
            state.putString("image_time",restoringImageTime);
            state.putBoolean("image_save_pending",imageSavePending);
        }else if(recognizingImageUri!=null){state.putString("image_uri",recognizingImageUri.toString());state.putBoolean("image_recognize",true);}
        if(state.containsKey("image_uri"))state.putString("image_import_key",imageImportKey);
    }
    @Override protected void onDestroy(){
        renderGeneration++;imageImportGeneration++;
        if(recognizingImageDialog!=null&&recognizingImageDialog.isShowing())recognizingImageDialog.dismiss();
        if(editingImageDialog!=null&&editingImageDialog.isShowing())editingImageDialog.dismiss();
        if(!isChangingConfigurations()){
            if(recognizingImageUri!=null)releaseImageUri(recognizingImageUri);
            if(editingImageUri!=null)releaseImageUri(editingImageUri);
            if(restoringImageUri!=null)releaseImageUri(restoringImageUri);
        }
        super.onDestroy();
    }
}
