package cn.courseinbox.companion;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.text.InputType;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.net.URI;

public final class ComputerActivity extends Activity {
    private static final int GREEN=Color.rgb(36,91,72), INK=Color.rgb(33,56,49), MUTED=Color.rgb(112,129,120), BG=Color.rgb(246,247,244);
    private EditText server,token,computerName;
    private TextView computerStatus,permissionStatus,syncStatus,syncHint;
    private Button pairButton,permissionButton,syncButton;
    private AlertDialog pairingDialog;
    private EndpointDraft endpointDraft;
    private final Handler handler=new Handler();
    private final Runnable update=new Runnable(){public void run(){refreshStatus();handler.postDelayed(this,1500);}};

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(BG);getWindow().setNavigationBarColor(BG);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setFitsSystemWindows(true);scroll.setBackgroundColor(BG);
        LinearLayout layout=column();layout.setPadding(dp(22),dp(28),dp(22),dp(24));scroll.addView(layout);setContentView(scroll);
        LinearLayout header=new LinearLayout(this);header.setGravity(Gravity.CENTER_VERTICAL);
        TextView brand=label("CampusInbox",15,GREEN,true);header.addView(brand,new LinearLayout.LayoutParams(0,-2,1));
        Button settings=button(header,"设置",false,this::showSettings);settings.setMinWidth(0);settings.setLayoutParams(new LinearLayout.LayoutParams(-2,-2));
        layout.addView(header);
        TextView title=label("手机连接",30,INK,true);title.setPadding(0,dp(22),0,dp(8));layout.addView(title);
        layout.addView(label("把学习通通知同步到电脑",14,MUTED,false));

        LinearLayout computer=card(layout);computer.addView(label("01  连接电脑",12,MUTED,false));
        computerStatus=label("尚未配对",20,INK,true);space(computerStatus,12,8);computer.addView(computerStatus);
        pairButton=button(computer,"连接电脑",true,this::showPairing);

        LinearLayout permission=card(layout);permission.addView(label("02  通知权限",12,MUTED,false));
        permissionStatus=label("尚未开启",18,INK,true);space(permissionStatus,12,8);permission.addView(permissionStatus);
        permissionButton=button(permission,"开启通知权限",false,()->startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));

        LinearLayout sync=card(layout);sync.addView(label("03  同步通知",12,MUTED,false));
        syncStatus=label("等待新通知",20,INK,true);space(syncStatus,12,8);sync.addView(syncStatus);
        syncHint=label("",13,MUTED,false);space(syncHint,0,12);sync.addView(syncHint);
        syncButton=button(sync,"同步一次",false,()->{
            if(CourseNotificationService.isConnected())CourseNotificationService.inspectVisibleNotifications(this);
            NotificationQueue.flush(this);refreshStatus();
            Toast.makeText(this,"正在尝试同步，请在电脑收件箱查看",Toast.LENGTH_SHORT).show();
        });
        TextView note=label("电脑不在线时，已采集的通知会留在手机等待同步。",12,MUTED,false);space(note,20,0);layout.addView(note);
        refreshStatus();
    }

    private void showPairing() {
        SharedPreferences prefs=NotificationQueue.preferences(this);
        LinearLayout form=column();form.setPadding(dp(24),dp(8),dp(24),dp(12));
        form.addView(label("从电脑“手机连接”页复制配对信息。",13,MUTED,false));
        computerName=field(form,"电脑名称",prefs.getString("target_name",""),"CourseInbox-xxxxxxxx",false);
        token=field(form,"配对令牌",prefs.getString("token",""),"粘贴电脑上的配对令牌",true);
        server=field(form,"电脑地址（可选）",prefs.getString("server",""),"自动寻找失败时填写",false);
        endpointDraft=new EndpointDraft(server.getText().toString());
        server.addTextChangedListener(new TextWatcher(){
            public void beforeTextChanged(CharSequence value,int start,int count,int after){}
            public void onTextChanged(CharSequence value,int start,int before,int count){endpointDraft.edited(value.toString());}
            public void afterTextChanged(Editable value){}
        });
        ScrollView scroll=new ScrollView(this);scroll.addView(form);
        AlertDialog.Builder builder=new AlertDialog.Builder(this).setTitle("连接电脑").setView(scroll)
            .setNegativeButton("取消",null).setPositiveButton("保存并连接",null);
        if(!prefs.getString("paired_device_id","").isEmpty())builder.setNeutralButton("更换电脑",null);
        pairingDialog=builder.create();pairingDialog.setOnDismissListener(dialog->{server=null;token=null;computerName=null;endpointDraft=null;pairingDialog=null;});
        pairingDialog.show();
        pairingDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view->{
            if(saveConfiguration()){NotificationQueue.pair(this);pairingDialog.dismiss();refreshStatus();}
        });
        Button change=pairingDialog.getButton(AlertDialog.BUTTON_NEUTRAL);
        if(change!=null)change.setOnClickListener(view->new AlertDialog.Builder(this).setTitle("更换配对电脑？")
            .setMessage("待同步通知会保留。更换后填写新电脑的配对信息。")
            .setNegativeButton("取消",null).setPositiveButton("更换",(dialog,which)->{
                synchronized(ComputerDiscovery.CONFIG_LOCK){prefs.edit().remove("paired_device_id").remove("paired_name").putBoolean("pairing_required",true)
                    .putInt("config_generation",prefs.getInt("config_generation",0)+1).putString("last_status","请重新配对电脑。").commit();}
                computerName.setText("");token.setText("");server.setText("");refreshStatus();
            }).show());
    }

    private boolean saveConfiguration() {
        SharedPreferences prefs=NotificationQueue.preferences(this);
        String endpoint=server.getText().toString().trim(),secret=token.getText().toString().trim(),name=computerName.getText().toString().trim();
        try {
            if(!endpoint.isEmpty()&&!NotificationQueue.allowedEndpoint(new URI(endpoint))){server.setError("请填写电脑的局域网服务地址");return false;}
        }catch(Exception error){server.setError("地址格式不正确");return false;}
        if(secret.length()<24){token.setError("请复制完整配对令牌");return false;}
        if(!name.isEmpty()&&!name.matches("CourseInbox-[0-9a-f]{8}")){computerName.setError("请复制电脑页面上的名称");return false;}
        synchronized(ComputerDiscovery.CONFIG_LOCK) {
            boolean changed=!endpoint.equals(prefs.getString("server",""))||!secret.equals(prefs.getString("token",""))||!name.equals(prefs.getString("target_name",""));
            boolean changedToken=!secret.equals(prefs.getString("token",""))&&!prefs.getString("paired_device_id","").isEmpty();
            SharedPreferences.Editor editor=prefs.edit().putString("server",endpoint).putString("token",secret).putString("target_name",name);
            if(changed)editor.putInt("config_generation",prefs.getInt("config_generation",0)+1);
            if(changedToken)editor.putBoolean("pairing_required",true);
            if(!editor.commit()){Toast.makeText(this,"保存失败，请重试",Toast.LENGTH_SHORT).show();return false;}
        }
        endpointDraft.saved(endpoint);return true;
    }

    private void showSettings() {
        SharedPreferences prefs=NotificationQueue.preferences(this);
        new AlertDialog.Builder(this).setTitle("设置").setItems(new String[]{"同步范围","连接帮助"},(dialog,which)->{
            if(which==1){new AlertDialog.Builder(this).setTitle("连接帮助")
                .setMessage("连接失败：确认电脑服务正在运行，手机与电脑连接同一网络；在配对窗口填写电脑当前地址再试。\n\n没有收到消息：检查通知权限，并确认学习通通知仍在通知栏，然后点击“同步一次”。系统只提供摘要时，请在学习通查看完整内容。")
                .setPositiveButton("知道了",null).show();return;}
            LinearLayout form=column();form.setPadding(dp(24),0,dp(24),dp(8));
            EditText scope=field(form,"班级 / 分组（可选）",prefs.getString("scope",""),"例如：软件工程1班",false);
            EditText packages=field(form,"接收应用（包名，每行一个）",prefs.getString("packages","com.chaoxing.mobile"),"com.chaoxing.mobile",false);
            packages.setSingleLine(false);packages.setMinLines(2);
            ScrollView scroll=new ScrollView(this);scroll.addView(form);
            new AlertDialog.Builder(this).setTitle("同步范围").setView(scroll).setNegativeButton("取消",null)
                .setPositiveButton("保存",(ignored,index)->{prefs.edit().putString("scope",scope.getText().toString().trim()).putString("packages",packages.getText().toString().trim()).apply();Toast.makeText(this,"同步范围已保存",Toast.LENGTH_SHORT).show();}).show();
        }).show();
    }

    private void refreshStatus() {
        if(computerStatus==null)return;
        SharedPreferences prefs=NotificationQueue.preferences(this);
        String paired=prefs.getString("paired_name",""),last=prefs.getString("last_status","");
        boolean hasComputer=!prefs.getString("paired_device_id","").isEmpty(),required=prefs.getBoolean("pairing_required",false),listening=CourseNotificationService.isConnected();
        boolean searching=last.startsWith("正在寻找并验证");
        computerStatus.setText(required?"需要重新配对":hasComputer?"已配对 · "+paired:"尚未配对");
        pairButton.setText(required?"重新连接":hasComputer?"修改配对":"连接电脑");
        permissionStatus.setText(listening?"通知访问已连接":"通知访问未连接");
        permissionStatus.setTextColor(listening?GREEN:INK);permissionButton.setText(listening?"管理通知权限":"开启 / 检查通知权限");
        int queued=NotificationQueue.count(this);
        syncStatus.setText(queued>0?queued+" 条等待同步":"暂无待传通知");
        String hint="新通知会自动尝试同步，也可补收通知栏中的消息。";
        if(required)hint="重新连接电脑后可继续同步。";
        else if(searching)hint="正在寻找电脑，请稍候…";
        else if(!hasComputer)hint=ConnectionStatus.failed(last)?"连接未成功，请检查网络、电脑地址和配对信息。":"先连接电脑，再开启通知权限。";
        else if(last.contains("队列文件异常"))hint="待传通知存储异常，请保留应用数据并检查。";
        else if(queued>=200)hint="待传通知已满，请连接电脑后同步。";
        else if(last.contains("拒绝")||last.contains("验证失败")||last.contains("不匹配"))hint="连接验证失败，请核对配对信息和接收应用。";
        else if(ConnectionStatus.failed(last))hint="连接未成功，请检查网络、电脑地址和配对信息。";
        else if(!listening)hint="开启通知权限后才能采集新通知。";
        syncHint.setText(hint);syncButton.setEnabled(hasComputer&&!required&&!searching);
        if(server!=null&&!server.hasFocus()&&hasComputer&&!required){
            String endpoint=endpointDraft.automatic(prefs.getString("server",""));if(!endpoint.contentEquals(server.getText()))server.setText(endpoint);
        }
    }

    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private LinearLayout column(){LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);return layout;}
    private GradientDrawable background(int color,int radius){GradientDrawable drawable=new GradientDrawable();drawable.setColor(color);drawable.setCornerRadius(dp(radius));return drawable;}
    private TextView label(String value,int size,int color,boolean bold){TextView text=new TextView(this);text.setText(value);text.setTextSize(size);text.setTextColor(color);if(bold)text.setTypeface(Typeface.DEFAULT,Typeface.BOLD);return text;}
    private void space(TextView view,int top,int bottom){view.setPadding(0,dp(top),0,dp(bottom));}
    private LinearLayout card(LinearLayout parent){LinearLayout card=column();card.setPadding(dp(20),dp(20),dp(20),dp(18));card.setBackground(background(Color.WHITE,18));LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.topMargin=dp(16);parent.addView(card,params);return card;}
    private EditText field(LinearLayout parent,String name,String value,String hint,boolean password){TextView title=label(name,13,MUTED,false);space(title,16,8);parent.addView(title);EditText edit=new EditText(this);edit.setTextSize(15);edit.setTextColor(INK);edit.setHintTextColor(MUTED);edit.setSingleLine(true);edit.setInputType(InputType.TYPE_CLASS_TEXT|(password?InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS));edit.setText(value);edit.setHint(hint);edit.setPadding(dp(12),dp(12),dp(12),dp(12));edit.setMinHeight(dp(48));GradientDrawable bg=background(BG,10);bg.setStroke(dp(1),Color.rgb(224,231,224));edit.setBackground(bg);parent.addView(edit,new LinearLayout.LayoutParams(-1,-2));return edit;}
    private Button button(LinearLayout parent,String name,boolean primary,Runnable action){Button button=new Button(this);button.setText(name);button.setAllCaps(false);button.setTextSize(14);button.setTextColor(primary?Color.WHITE:GREEN);button.setMinHeight(dp(48));button.setPadding(dp(16),dp(10),dp(16),dp(10));button.setBackgroundTintList(null);button.setBackground(background(primary?GREEN:Color.rgb(234,241,233),10));button.setOnClickListener(view->action.run());parent.addView(button,new LinearLayout.LayoutParams(-1,-2));return button;}
    @Override protected void onResume(){super.onResume();handler.removeCallbacks(update);handler.post(update);NotificationQueue.flush(this);}
    @Override protected void onPause(){super.onPause();handler.removeCallbacks(update);}
}
