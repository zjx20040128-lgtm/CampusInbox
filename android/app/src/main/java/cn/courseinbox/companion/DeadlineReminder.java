package cn.courseinbox.companion;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import java.util.*;

/** One replaceable system alarm for local confirmed tasks, independent of the PC. */
public final class DeadlineReminder extends BroadcastReceiver {
    private static final String CHANNEL="task_deadlines",ACTION="cn.courseinbox.companion.CHECK_DEADLINES";
    private static SharedPreferences prefs(Context c){return c.getSharedPreferences("deadline-reminders",Context.MODE_PRIVATE);}
    public static boolean enabled(Context c){return prefs(c).getBoolean("enabled",true);}
    public static void setEnabled(Context c,boolean enabled){prefs(c).edit().putBoolean("enabled",enabled).apply();refresh(c);}
    public static void refresh(Context c){Context app=c.getApplicationContext();MobileStore.WORKER.execute(()->run(app));}
    public static boolean canShow(Context c){
        if(Build.VERSION.SDK_INT>=33&&c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return false;
        NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        if(manager==null||!manager.areNotificationsEnabled())return false;
        NotificationChannel channel=manager.getNotificationChannel(CHANNEL);
        return channel==null||channel.getImportance()!=NotificationManager.IMPORTANCE_NONE;
    }
    @Override public void onReceive(Context c,Intent intent){
        String action=intent==null?"":intent.getAction();
        if(!Arrays.asList(ACTION,Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED,Intent.ACTION_TIME_CHANGED,Intent.ACTION_TIMEZONE_CHANGED).contains(action))return;
        PendingResult pending=goAsync();Context app=c.getApplicationContext();
        MobileStore.WORKER.execute(()->{try{run(app);}finally{pending.finish();}});
    }
    private static void run(Context c){
        SharedPreferences settings=prefs(c);
        AlarmManager alarms=(AlarmManager)c.getSystemService(Context.ALARM_SERVICE);
        PendingIntent alarm=PendingIntent.getBroadcast(c,0,new Intent(c,DeadlineReminder.class).setAction(ACTION),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        try{
            NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
            List<LocalInbox.Task> tasks=MobileStore.get(c).tasks();
            Map<String,LocalInbox.Task> active=new HashMap<>();
            for(LocalInbox.Task task:tasks)if(Arrays.asList("pending","in_progress","done").contains(task.status)&&!task.deadline.isEmpty())active.put(task.id,task);
            // Dismiss notifications for a submitted, cancelled, removed or rescheduled task.
            if(manager!=null)for(android.service.notification.StatusBarNotification notice:manager.getActiveNotifications()){
                String tag=notice.getTag();if(tag==null||!tag.startsWith("deadline:"))continue;
                LocalInbox.Task task=active.get(tag.substring(9));
                if(!enabled(c)||task==null||!task.deadline.equals(notice.getNotification().extras.getString("courseinbox_deadline")))manager.cancel(tag,2);
            }
            if(!enabled(c)||!canShow(c)){if(alarms!=null)alarms.cancel(alarm);return;}
            Set<String> sent=new HashSet<>(settings.getStringSet("sent",Collections.emptySet()));
            long now=System.currentTimeMillis(),next=Long.MAX_VALUE;
            for(LocalInbox.Task task:active.values()){
                DeadlinePlan.Event event=DeadlinePlan.next(task.id,task.deadline,task.status,now,sent);
                if(event!=null&&event.at<=now){
                    if(show(c,task,event))sent.add(event.key);
                    else {next=Math.min(next,now+3600000L);continue;}
                    event=DeadlinePlan.next(task.id,task.deadline,task.status,now,sent);
                }
                if(event!=null)next=Math.min(next,event.at);
            }
            // Drop keys of removed tasks; keep old deadlines so a revert cannot spam.
            Set<String> ids=new HashSet<>();for(LocalInbox.Task task:tasks)ids.add(task.id);
            sent.removeIf(key->!ids.contains(key.split("\\|",2)[0]));
            settings.edit().putStringSet("sent",sent).putString("error","").commit();
            if(alarms!=null){
                if(next==Long.MAX_VALUE)alarms.cancel(alarm);
                else alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,Math.max(now+1000,next),alarm);
            }
        }catch(Exception error){
            settings.edit().putString("error","截止提醒暂未安排，请重新打开应用重试。").apply();
            if(alarms!=null)try{alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,System.currentTimeMillis()+3600000L,alarm);}catch(RuntimeException ignored){}
        }
    }
    public static String status(Context c){
        if(!enabled(c))return "截止提醒已关闭";
        if(!canShow(c))return "需要允许 CampusInbox 发送截止通知";
        return prefs(c).getString("error","").isEmpty()?"提前 1 天、2 小时及到期提醒；系统省电可能延迟。":prefs(c).getString("error","");
    }
    private static boolean show(Context c,LocalInbox.Task task,DeadlinePlan.Event event){
        try{
            NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL,"任务截止提醒",NotificationManager.IMPORTANCE_HIGH));
            Intent open=new Intent(c,MainActivity.class).setAction("cn.courseinbox.companion.OPEN_TASK").setData(Uri.parse("courseinbox://task/"+task.id)).putExtra(MainActivity.EXTRA_TASK_ID,task.id).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent tap=PendingIntent.getActivity(c,0,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
            String title=event.level.equals("overdue")?"任务已到期，请核对提交":event.level.equals("date")?"任务今天截止":"任务即将截止";
            String body=task.course+" · "+task.title+"\n截止："+task.deadline+(task.deadline.length()==10?"（具体时间待核对）":"");
            android.os.Bundle extras=new android.os.Bundle();extras.putString("courseinbox_deadline",task.deadline);
            manager.notify("deadline:"+task.id,2,new Notification.Builder(c,CHANNEL).setSmallIcon(R.drawable.ic_courseinbox_notification).setContentTitle(title).setContentText(body).setStyle(new Notification.BigTextStyle().bigText(body)).setContentIntent(tap).setExtras(extras).setAutoCancel(true).setCategory(Notification.CATEGORY_REMINDER).setVisibility(Notification.VISIBILITY_PRIVATE).build());
            return true;
        }catch(RuntimeException error){return false;}
    }
}
