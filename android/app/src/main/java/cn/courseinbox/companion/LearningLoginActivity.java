package cn.courseinbox.companion;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.view.View;
import android.view.Gravity;
import android.view.WindowManager;
import android.graphics.Color;
import android.webkit.*;
import android.window.OnBackInvokedDispatcher;
import android.widget.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.List;
import org.json.*;

/** Official login session lives in this app's WebView, never on a paired computer. */
public final class LearningLoginActivity extends Activity {
    private WebView web;private TextView status,origin;private LinearLayout readingNavigation;private String scripts="",loginLayout="",pageLayout="",imageCompatibility="";private boolean resumed,busy,originalLogin,readPassFinished;private int generation;
    private volatile LearningReadFlow readFlow;
    private final Handler handler=new Handler();
    private final Runnable scan=this::scan;
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);MobileUi ui=new MobileUi(this);int background=Color.rgb(244,246,251);getWindow().setStatusBarColor(background);getWindow().setNavigationBarColor(background);getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        LinearLayout root=ui.column();root.setFitsSystemWindows(true);root.setPadding(ui.dp(12),ui.dp(8),ui.dp(12),0);root.setBackgroundColor(background);setContentView(root);
        LinearLayout header=new LinearLayout(this);header.setGravity(Gravity.CENTER_VERTICAL);root.addView(header);
        header.addView(smallButton(ui,"‹ 返回",this::goBack),new LinearLayout.LayoutParams(0,-2,1));
        LinearLayout.LayoutParams refreshParams=new LinearLayout.LayoutParams(0,-2,1);refreshParams.leftMargin=ui.dp(4);refreshParams.rightMargin=ui.dp(4);
        header.addView(smallButton(ui,"刷新",()->confirmReload(false)),refreshParams);
        header.addView(smallButton(ui,"说明",this::showInstructions),new LinearLayout.LayoutParams(0,-2,1));
        TextView heading=ui.text("连接学习通",20,MobileUi.INK,true);heading.setGravity(Gravity.CENTER);root.addView(heading);
        origin=ui.text("学习通官方页面 · HTTPS",11,Color.rgb(83,112,156),false);origin.setGravity(Gravity.CENTER);root.addView(origin);
        status=ui.text("正在打开学习通官方页面…",12,MobileUi.MUTED,false);status.setGravity(Gravity.CENTER);root.addView(status);
        readingNavigation=new LinearLayout(this);readingNavigation.setVisibility(View.GONE);root.addView(readingNavigation);
        readingNavigation.addView(smallButton(ui,"聊天消息",()->chooseSource(LearningUrls.CHAT)),new LinearLayout.LayoutParams(0,-2,1));
        readingNavigation.addView(smallButton(ui,"课程通知",()->chooseSource(LearningUrls.NOTICES)),new LinearLayout.LayoutParams(0,-2,1));
        web=new WebView(this);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);settings.setSupportZoom(true);settings.setBuiltInZoomControls(true);settings.setDisplayZoomControls(false);settings.setUseWideViewPort(true);settings.setLoadWithOverviewMode(true);
        settings.setUserAgentString("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36");
        CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,true);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){if(!LearningUrls.allowed(request.getUrl().toString())){status.setText("这个入口需要在学习通 App 中查看；请使用上方的聊天或通知入口。");return true;}return false;}
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){generation++;busy=false;readPassFinished=false;if(readFlow!=null)readFlow=readFlow.forPage();handler.removeCallbacksAndMessages(null);configurePage(url);status.setText("正在加载官方页面…");syncStatus("正在打开"+LearningReadFlow.pageLabel(url)+"…");}
            @Override public void onPageFinished(WebView view,String url){
                if(view!=web||!url.equals(view.getUrl()))return;
                if(!LearningUrls.allowed(url)){status.setText("页面来源不受支持。");return;}
                configurePage(url);
                // Secure image compatibility is independent of the optional phone layout.
                if(!imageCompatibility.isEmpty())view.evaluateJavascript(imageCompatibility,null);
                String layout=LearningUrls.login(url)?loginLayout:pageLayout;
                String adapter=LearningUrls.login(url)?"CourseInboxMobileLoginUI":"CourseInboxMobilePageUI";
                if(!originalLogin&&!layout.isEmpty()){
                    final LearningPageGuard request=new LearningPageGuard(generation,url);
                    view.evaluateJavascript(layout+"\nBoolean(globalThis."+adapter+"&&"+adapter+".apply())",applied->{
                        if(!originalLogin&&request.permits(generation,web==null?null:web.getUrl(),view==web&&!isFinishing())&&"true".equals(applied)){
                            view.getSettings().setLoadWithOverviewMode(false);view.setInitialScale(100);
                        }
                    });
                }
                if(resumed){handler.removeCallbacks(scan);handler.post(scan);}
                MobileStore.WORKER.execute(()->CookieManager.getInstance().flush());
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){if(request.isForMainFrame())readerError("官方页面连接失败，可点上方刷新重试。");}
            @Override public void onReceivedSslError(WebView view,SslErrorHandler ssl,SslError error){ssl.cancel();readerError("官方页面安全连接失败，可稍后刷新重试。");}
        });
        web.setWebChromeClient(new WebChromeClient());
        if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::goBack);
        web.setDownloadListener((url,userAgent,contentDisposition,mime,length)->status.setText("附件请在学习通中核对；本机消息原文已保留。"));
        try{scripts=asset("parser.js")+"\n"+asset("notices.js")+"\n"+asset("mobile-reader.js");}
        catch(IOException error){status.setText("消息读取资源缺失，请重新安装完整 APK。");}
        try{loginLayout=asset("mobile-login-ui.js");}catch(IOException ignored){/* Original official login remains usable if presentation assets are unavailable. */}
        try{pageLayout=asset("mobile-page-ui.js");}catch(IOException ignored){/* Unknown or unavailable layouts retain the official overview. */}
        try{imageCompatibility=asset("mobile-images.js");}catch(IOException ignored){/* Never relax mixed-content or TLS checks if the adapter is missing. */}
        String url=getIntent().getStringExtra("url");url=LearningUrls.allowed(url)?url:LearningUrls.PORTAL;
        readFlow=new LearningReadFlow(url,getIntent().getBooleanExtra("return_after_read",false));navigate(url);
    }
    private Button smallButton(MobileUi ui,String label,Runnable action){Button button=new Button(this);button.setText(label);button.setAllCaps(false);button.setTextSize(14);button.setTextColor(Color.rgb(57,125,234));button.setMinWidth(0);button.setMinimumWidth(0);button.setMinHeight(ui.dp(48));button.setSingleLine(false);button.setPadding(ui.dp(4),ui.dp(8),ui.dp(4),ui.dp(8));button.setBackgroundTintList(null);button.setBackground(ui.background(Color.WHITE,12));button.setOnClickListener(v->action.run());return button;}
    private void configurePage(String url){web.getSettings().setLoadWithOverviewMode(true);web.setInitialScale(0);if(LearningUrls.login(url))readingNavigation.setVisibility(View.GONE);try{origin.setText("官方页面 · "+new java.net.URI(url).getHost());}catch(Exception ignored){origin.setText("学习通官方页面 · HTTPS");}}
    private void showInstructions(){new AlertDialog.Builder(this).setTitle("登录说明").setMessage("这里使用学习通官方页面，账号、验证码和扫码确认由学习通处理。\n\n二维码显示在本手机时，请先展示到另一块屏幕，再用学习通 App 扫码。\n\n学校验证或页面异常时，可切回官方原版。上方“刷新”会重新加载当前页面，并重新读取当前页可见消息；不会清除登录会话或手机存档。").setPositiveButton("知道了",null).setNeutralButton(originalLogin?"手机布局":"官方原版",(d,w)->confirmReload(true)).show();}
    private void confirmReload(boolean switchLayout){
        if(web==null||!LearningUrls.allowed(web.getUrl())){status.setText("当前页面不可刷新，请重新打开学习通。");return;}
        final LearningPageGuard request=new LearningPageGuard(generation,web.getUrl());
        new AlertDialog.Builder(this).setTitle(switchLayout?"切换页面布局？":"刷新当前页面？")
            .setMessage("当前页面会重新加载，未提交的登录信息或正在编辑的消息可能丢失。登录会话和手机存档会保留。")
            .setNegativeButton("取消",null).setPositiveButton(switchLayout?"继续切换":"刷新",(d,w)->{
                if(!request.permits(generation,web==null?null:web.getUrl(),resumed&&web!=null&&!isFinishing())){status.setText("页面已变化，请在当前页面重新选择操作。");return;}
                if(switchLayout)originalLogin=!originalLogin;
                readFlow=new LearningReadFlow(readFlow.targetUrl(),readFlow.isAutomatic());
                generation++;busy=false;handler.removeCallbacksAndMessages(null);configurePage(web.getUrl());status.setText("正在刷新当前官方页面…");web.reload();
            }).show();
    }
    private String asset(String name)throws IOException{try(InputStream input=getAssets().open(name);ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] bytes=new byte[8192];int count;while((count=input.read(bytes))!=-1)output.write(bytes,0,count);return new String(output.toByteArray(),StandardCharsets.UTF_8);}}
    private void navigate(String url){if(web!=null&&LearningUrls.allowed(url))web.loadUrl(url);}
    private void chooseSource(String url){readFlow=new LearningReadFlow(url,false);navigate(url);}
    private void syncStatus(String value){if(readFlow!=null&&readFlow.isAutomatic())NotificationQueue.preferences(this).edit().putString("learning_sync_status",value).apply();}
    private void readerError(String value){status.setText(value);NotificationQueue.preferences(this).edit().putString("web_reader_error",value).apply();syncStatus(value);}
    private void goBack(){if(readFlow!=null&&readFlow.isAutomatic())finish();else if(web!=null&&web.canGoBack())web.goBack();else finish();}
    @Override public void onBackPressed(){goBack();}
    private void scan(){
        if(!resumed||busy||scripts.isEmpty()||!LearningUrls.allowed(web.getUrl()))return;
        if(readFlow.saving()){handler.postDelayed(scan,300);return;}
        if(readFlow.shouldReturn(web.getUrl())){completePass(readFlow);return;}
        busy=true;final int epoch=generation;final String pageUrl=web.getUrl();
        if(readFlow.awaitingSnapshot()){readSnapshot(epoch,pageUrl,readFlow.currentRead(),0);return;}
        final long readId=readFlow.startRead();
        NotificationQueue.preferences(this).edit().putString("web_reader_page",LearningReadFlow.pageLabel(pageUrl)).apply();
        String start="window.__ciMobileReadRequest="+readId+";window.__ciMobileNoticeLimit="+readFlow.nextNoticeLimit()+";\n"+scripts+"\n(function(){var request=window.__ciMobileReadRequest;window.__ciMobileSnapshot='';CourseInboxMobileReader.poll({notice_limit:window.__ciMobileNoticeLimit}).then(function(r){r.read_request=request;window.__ciMobileSnapshot=JSON.stringify(r)}).catch(function(){window.__ciMobileSnapshot=JSON.stringify({read_request:request,state:'error',authenticated:false,messages:[],url:location.href})});})()";
        web.evaluateJavascript(start,ignored->handler.postDelayed(()->readSnapshot(epoch,pageUrl,readId,0),300));
    }
    private void readSnapshot(int epoch,String pageUrl,long readId,int attempt){
        if(!resumed||epoch!=generation||!pageUrl.equals(web.getUrl())||readFlow.currentRead()!=readId)return;
        if(attempt>100){if(!readFlow.consumeRead(readId))return;busy=false;readerError("网页读取超时，尚未取得本轮结果，稍后重试。");handler.postDelayed(scan,15000);return;}
        web.evaluateJavascript("window.__ciMobileSnapshot||''",encoded->{
            if(!resumed||epoch!=generation||!pageUrl.equals(web.getUrl())||readFlow.currentRead()!=readId)return;
            try{
                Object decoded=new JSONTokener(encoded).nextValue();String raw=decoded instanceof String?(String)decoded:"";
                if(raw.isEmpty()){handler.postDelayed(()->readSnapshot(epoch,pageUrl,readId,attempt+1),500);return;}
                if(raw.length()>3000000)throw new IOException("读取内容超限，请打开较小的会话。");
                JSONObject snapshot=new JSONObject(raw);
                if(snapshot.optLong("read_request",-1)!=readId){handler.postDelayed(()->readSnapshot(epoch,pageUrl,readId,attempt+1),500);return;}
                if(!pageUrl.equals(snapshot.optString("url")))throw new IOException("页面已变化，请重试读取。");
                if(!readFlow.consumeRead(readId))return;
                apply(snapshot,epoch,pageUrl);
            }catch(Exception error){readFlow.consumeRead(readId);busy=false;readerError("网页结果暂未读取，请刷新重试（"+error.getClass().getSimpleName()+"）。");handler.postDelayed(scan,15000);}
        });
    }
    private void apply(JSONObject snapshot,int epoch,String pageUrl){
        String state=snapshot.optString("state");SharedPreferences prefs=NotificationQueue.preferences(this);
        prefs.edit().putString("web_reader_state",state).putString("web_reader_page",LearningReadFlow.pageLabel(pageUrl)).apply();
        if(state.equals("waiting_scan")){
            readingNavigation.setVisibility(View.GONE);
            boolean hadSession=prefs.getString("learning_state","idle").equals("connected")||prefs.getString("learning_state","idle").equals("partial");
            prefs.edit().putString("learning_state",hadSession?"expired":"waiting_scan").apply();
            status.setText(hadSession?"登录已失效，请重新登录。":"请扫码确认，或切换账号登录");syncStatus("请完成学习通登录，随后继续读取课程通知。");busy=false;handler.postDelayed(scan,4000);return;
        }
        if(!snapshot.optBoolean("authenticated",false)){
            if(state.equals("unrecognized"))prefs.edit().putString("learning_state","unverified").apply();
            else if(state.equals("error"))prefs.edit().putString("learning_state","error").apply();
            readingNavigation.setVisibility(View.GONE);String pending=state.equals("error")?"网页读取暂时失败，可刷新或查看官方原版。":state.equals("loading")?"页面内容仍在加载，稍后自动读取。":"当前页面暂未识别，可刷新或查看官方原版。";status.setText(pending);syncStatus(pending);busy=false;handler.postDelayed(scan,10000);return;
        }
        if(prefs.getString("learning_session_scope","").isEmpty())prefs.edit().putString("learning_session_scope",UUID.randomUUID().toString()).apply();
        prefs.edit().putString("learning_state",state.equals("partial")?"partial":"connected").apply();
        readingNavigation.setVisibility(View.VISIBLE);
        String next=readFlow.nextPage(pageUrl,state,true);
        if(!next.isEmpty()){busy=false;String pending="已登录，正在打开"+LearningReadFlow.pageLabel(next)+"…";status.setText(pending);syncStatus(pending);navigate(next);return;}
        if(!LearningUrls.collectible(pageUrl)){
            status.setText("已登录 · 当前是门户，尚未读取课程通知");syncStatus("已确认登录，但课程通知尚未打开；可点上方课程通知重试。");busy=false;handler.postDelayed(scan,30000);return;
        }
        final int listed=snapshot.optInt("listed_count",0),inspected=snapshot.optInt("inspected_count",Math.min(5,listed)),unread=snapshot.optInt("failed_count",0);
        final boolean notices=pageUrl.startsWith("https://notice.chaoxing.com/");final LearningReadFlow flow=readFlow;
        final long batchRead=flow.currentRead();
        flow.startSaving();
        prefs.edit().putInt("web_listed_count",listed).putInt("web_detail_count",snapshot.optInt("detail_count",0)).putInt("web_failed_count",unread).apply();
        status.setText("正在保存已读取的消息…");syncStatus("正在读取并保存课程通知…");
        JSONArray messages=snapshot.optJSONArray("messages");
        MobileStore.WORKER.execute(()->{
            int saved=0,failed=0;String saveError="";
            List<LocalInbox.Task> before=null;
            try{before=MobileStore.get(this).tasks();}catch(IOException error){failed++;saveError=error.getClass().getSimpleName();}
            if(messages!=null)for(int i=0;i<Math.min(300,messages.length());i++)try{JSONObject job=messages.getJSONObject(i);if(MobileStore.web(this,job))saved++;}catch(Exception error){failed++;saveError=error.getClass().getSimpleName();}
            int discovered=0;boolean alerted=false;MobileTaskAlerts.Batch alerts=null;
            if(before!=null)try{
                LocalInbox inbox=MobileStore.get(this);alerts=MobileTaskAlerts.plan(before,inbox.tasks(),inbox.messages());
                discovered=alerts.count;if(discovered>0&&!flow.isAutomatic())alerted=MobileAlert.showTasks(this,alerts);
            }catch(IOException error){failed++;saveError=error.getClass().getSimpleName();}
            final int added=saved,errors=failed,newTasks=discovered;
            if(flow.isAutomatic()&&notices){
                flow.record(listed,inspected,unread,added,newTasks,errors,alerts);
                if(discovered>0&&flow.claimAlert())flow.alertResult(MobileAlert.showTasks(getApplicationContext(),flow.alertPlan(),flow.alertKey()));
                alerted=flow.alertRequested();
            }else flow.record(listed,inspected,unread,added,newTasks,errors);
            String result=LearningReadFlow.pageLabel(pageUrl)+"：检查 "+inspected+" 条；保存 "+saved+" 条；新增 "+discovered+" 项任务；未读 "+unread+" 条；保存失败 "+failed+" 条。";
            prefs.edit().putString("web_capture_status",result).putString("web_save_error",saveError).putString("web_reader_error",unread>0?"本轮部分正文未取得":"")
                .putString("web_alert_status",(flow.isAutomatic()?flow.alertPlan().count:discovered)==0?"本轮没有新增任务，不重复提醒。":alerted?"已请求系统显示新任务提醒。":"任务已保存，但未能请求系统提醒，请检查本应用通知权限与通知频道。").apply();
            if(notices){android.content.SharedPreferences.Editor update=prefs.edit().putLong("web_notice_checked_at",System.currentTimeMillis()).putString("web_notice_capture_status",result);if(flow==readFlow)update.putString("learning_sync_status",flow.isAutomatic()?flow.summary():result);update.apply();}
            try{CookieManager.getInstance().flush();}catch(RuntimeException error){prefs.edit().putString("web_save_error","会话刷新："+error.getClass().getSimpleName()).apply();}finally{flow.finishSaving();}
            runOnUiThread(()->{
                if(!resumed||flow!=readFlow||web==null||!pageUrl.equals(web.getUrl())||flow.currentRead()!=batchRead||flow.awaitingSnapshot()||flow.saving())return;busy=false;handler.removeCallbacks(scan);
                if(flow.isAutomatic()&&notices){
                    status.setText(flow.summary());if(flow.shouldReturn(pageUrl)){completePass(flow);return;}
                }else status.setText(errors>0?"部分消息保存失败，请重试；原存档仍保留。":(state.equals("partial")?"部分内容待重试":"已登录")+" · 本轮保存 "+added+" 条，新增 "+newTasks+" 项任务待确认");
                handler.postDelayed(scan,flow.hasMore()?800:30000);
            });
        });
    }
    private void completePass(LearningReadFlow flow){readPassFinished=true;Toast.makeText(this,flow.summary(),Toast.LENGTH_LONG).show();finish();}
    @Override protected void onResume(){super.onResume();resumed=true;if(web!=null){web.onResume();busy=false;handler.postDelayed(scan,800);}}
    @Override protected void onPause(){if(!readPassFinished)syncStatus("本轮同步尚未完成，点击刷新可继续读取。");resumed=false;generation++;busy=false;handler.removeCallbacksAndMessages(null);if(web!=null)web.onPause();super.onPause();}
    @Override protected void onDestroy(){handler.removeCallbacksAndMessages(null);if(web!=null){web.stopLoading();web.destroy();web=null;}super.onDestroy();}
}
