package cn.courseinbox.companion;

import android.Manifest;
import android.app.Activity;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.provider.Settings;
import android.text.*;
import android.widget.*;
import java.text.DateFormat;
import java.util.*;
import java.util.concurrent.*;

/** Computer -> phone pairing and phone-local history. No WebView or external notification URL. */
public final class ComputerRemindersActivity extends Activity {
    private static final int REQUEST_NOTIFICATIONS=71;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private MobileUi ui;private ComputerReminderStore store;private TextView status;private EditText address,code,name;private LinearLayout history;private ScrollView scroll;
    private boolean focusHistory;
    private Button pair;private boolean pairing,historyLoading;private String pendingPermission="";
    private final Runnable refresh=new Runnable(){public void run(){refreshStatus();loadHistory();handler.postDelayed(this,3000);}};
    @Override public void onCreate(Bundle state){
        super.onCreate(state);ui=new MobileUi(this);store=ComputerReminderStore.get(this);ComputerReminderNotifications.channels(this);
        getWindow().setStatusBarColor(MobileUi.BG);getWindow().setNavigationBarColor(MobileUi.BG);
        focusHistory=historyIntent(getIntent());scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setFitsSystemWindows(true);scroll.setBackgroundColor(MobileUi.BG);
        LinearLayout body=ui.column();body.setPadding(ui.dp(22),ui.dp(24),ui.dp(22),ui.dp(28));scroll.addView(body);setContentView(scroll);
        body.addView(ui.smallAction("返回",this::finish));body.addView(ui.text("接收电脑提醒",28,MobileUi.INK,true));
        body.addView(ui.text("电脑后台采集学习通，手机在同一 Wi-Fi 接收新消息、任务与截止提醒。",14,MobileUi.MUTED,false));
        LinearLayout connection=ui.card(body);status=ui.text("",16,MobileUi.INK,true);connection.addView(status);
        ui.button(connection,"允许发送提醒通知",false,()->permission(""));
        ui.button(connection,"查看提醒历史",false,()->scroll.smoothScrollTo(0,history.getTop()));
        ui.button(connection,"开始 / 恢复接收",true,()->{if(permission("start"))startReceiving();});
        ui.button(connection,"停止接收",false,()->{try{ComputerReminderService.stop(this,false);refreshStatus();}catch(Exception error){toast("无法保存停止状态，请重试");}});
        ui.button(connection,"断开配对",false,()->new android.app.AlertDialog.Builder(this).setTitle("断开电脑配对？").setMessage("手机不再接收此电脑提醒，本地历史保留。也可在电脑页面撤销此设备。").setNegativeButton("取消",null).setPositiveButton("断开",(d,w)->{try{ComputerReminderService.stop(this,true);refreshStatus();}catch(Exception error){toast("无法保存断开状态，请重试");}}).show());
        LinearLayout form=ui.card(body);form.addView(ui.text("配对电脑",19,MobileUi.INK,true));
        form.addView(ui.text("在电脑“手机连接”页开启电脑提醒，复制局域网地址并生成 6 位配对码。",13,MobileUi.MUTED,false));
        address=ui.input(form,"电脑地址",store.session().endpoint);address.setSingleLine(true);address.setHint("http://192.168.1.8:8766");address.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);
        code=ui.input(form,"6 位配对码（5 分钟内有效）","");code.setSingleLine(true);code.setInputType(InputType.TYPE_CLASS_NUMBER);code.setFilters(new InputFilter[]{new InputFilter.LengthFilter(6)});
        name=ui.input(form,"此手机名称",store.name());name.setSingleLine(true);name.setFilters(new InputFilter[]{new InputFilter.LengthFilter(80)});
        pair=ui.button(form,"配对并开始接收",true,()->{if(permission("pair"))pair();});
        form.addView(ui.text("这里只需允许发送通知，无需开启通知读取权限。连接时会显示常驻通知；系统省电或强行停止应用可能中断接收。",12,MobileUi.MUTED,false));
        history=ui.column();body.addView(history);refreshStatus();loadHistory();
    }
    private boolean permission(String action){
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){pendingPermission=action;requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},REQUEST_NOTIFICATIONS);return false;}
        if(!new ComputerReminderNotifications(this).allowed()){
            startActivity(new Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,getPackageName()).putExtra(Settings.EXTRA_CHANNEL_ID,ComputerReminderNotifications.CHANNEL));toast("允许电脑提醒通知后，返回并点击配对或开始接收");return false;
        }
        if(action.isEmpty())toast("电脑提醒通知已允许");return true;
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request!=REQUEST_NOTIFICATIONS)return;String action=pendingPermission;pendingPermission="";if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED){if(action.equals("pair"))pair();else if(action.equals("start"))startReceiving();else refreshStatus();}else toast("未允许发送通知，尚未启动电脑提醒");}
    private void pair(){
        if(pairing)return;
        final String endpoint;try{endpoint=ComputerReminderProtocol.endpoint(address.getText().toString());}catch(IllegalArgumentException error){address.setError(error.getMessage());return;}
        final String digits=code.getText().toString().trim(),deviceName=name.getText().toString().trim();
        if(!digits.matches("[0-9]{6}")){code.setError("请输入 6 位数字配对码");return;}if(deviceName.isEmpty()||deviceName.length()>80){name.setError("请填写 1–80 字的手机名称");return;}
        final long generation;try{generation=store.beginPair();stopService(new Intent(this,ComputerReminderService.class));}catch(Exception error){toast("无法保存配对状态，请重试");return;}
        pairing=true;pair.setEnabled(false);refreshStatus();
        worker.execute(()->{
            boolean saved=false;String message="";
            try{ComputerReminderApi.Pair result=new ComputerReminderApi().pair(endpoint,digits,deviceName);saved=store.paired(generation,endpoint,result.token,result.deviceId,result.serverId,deviceName);}
            catch(Exception error){message=error instanceof ComputerReminderHttp.Failure?"配对失败：请检查配对码是否过期、已使用，或重新生成配对码":"未能配对，请检查同一 Wi-Fi、电脑地址和提醒服务";store.status(generation,message);}
            boolean success=saved;String feedback=message;
            runOnUiThread(()->{if(isDestroyed())return;pairing=false;pair.setEnabled(true);if(success&&store.session().generation==generation){code.setText("");startReceiving();}else if(!feedback.isEmpty())toast(feedback);refreshStatus();});
        });
    }
    private void startReceiving(){
        if(!store.session().paired()){toast("请先填写电脑地址与配对码");return;}
        if(!permission("start"))return;
        try{ComputerReminderService.start(this);toast("正在启动电脑提醒连接");}catch(Exception error){toast("未能启动，请检查通知权限并保持应用在前台重试");}refreshStatus();
    }
    private void refreshStatus(){if(status==null)return;ComputerReminderStore.Session s=store.session();status.setText(s.status+(s.enabled?"\n接收已开启":"\n接收已停止")+(!new ComputerReminderNotifications(this).allowed()?"\n需要允许发送电脑提醒通知":""));}
    private void loadHistory(){
        if(historyLoading||isDestroyed())return;historyLoading=true;
        worker.execute(()->{try{List<ComputerReminderStore.History> rows=store.history();runOnUiThread(()->{historyLoading=false;if(isDestroyed())return;history.removeAllViews();history.addView(ui.text("电脑提醒历史 · 最近 100 条",19,MobileUi.INK,true));if(rows.isEmpty())history.addView(ui.text("配对前的内容不会补发；新提醒成功显示后会保存在这里。",13,MobileUi.MUTED,false));for(ComputerReminderStore.History row:rows){LinearLayout card=ui.card(history);card.addView(ui.text(row.title,17,MobileUi.INK,true));card.addView(ui.text(row.body,14,MobileUi.INK,false));card.addView(ui.text("手机收到提醒："+DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(new Date(row.receivedAt)),11,MobileUi.MUTED,false));}if(focusHistory){focusHistory=false;history.post(()->scroll.smoothScrollTo(0,history.getTop()));}});}catch(Exception error){runOnUiThread(()->{historyLoading=false;if(!isDestroyed())toast("提醒历史读取失败，请保留应用数据后重试");});}});
    }
    @Override protected void onResume(){super.onResume();handler.post(refresh);}
    @Override protected void onPause(){handler.removeCallbacks(refresh);super.onPause();}
    @Override protected void onDestroy(){handler.removeCallbacksAndMessages(null);worker.shutdownNow();super.onDestroy();}
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);focusHistory=historyIntent(intent);loadHistory();}
    private static boolean historyIntent(Intent intent){return intent!=null&&"cn.courseinbox.companion.COMPUTER_HISTORY".equals(intent.getAction());}
    private void toast(String text){Toast.makeText(this,text,Toast.LENGTH_LONG).show();}
}
