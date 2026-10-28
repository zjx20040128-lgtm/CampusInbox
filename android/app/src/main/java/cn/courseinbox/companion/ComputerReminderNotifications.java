package cn.courseinbox.companion;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;

final class ComputerReminderNotifications implements ComputerReminderDelivery.Notices {
    static final String CHANNEL="computer_reminder_alerts",CONNECTION_CHANNEL="computer_reminder_connection";
    private final Context context;
    ComputerReminderNotifications(Context context){this.context=context;}
    static void channels(Context context){NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);if(manager==null)return;manager.createNotificationChannel(new NotificationChannel(CHANNEL,"电脑学习通提醒",NotificationManager.IMPORTANCE_HIGH));manager.createNotificationChannel(new NotificationChannel(CONNECTION_CHANNEL,"电脑提醒连接状态",NotificationManager.IMPORTANCE_LOW));}
    public boolean allowed(){
        NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);if(manager==null)return false;
        NotificationChannel channel=manager.getNotificationChannel(CHANNEL);
        return ComputerReminderProtocol.notificationPermission(Build.VERSION.SDK_INT,Build.VERSION.SDK_INT<33||context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED,manager.areNotificationsEnabled(),channel==null||channel.getImportance()!=NotificationManager.IMPORTANCE_NONE);
    }
    static PendingIntent history(Context context,String tag){Intent intent=new Intent(context,ComputerRemindersActivity.class).setAction("cn.courseinbox.companion.COMPUTER_HISTORY").setData(Uri.parse("courseinbox://computer-history/"+Uri.encode(tag))).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);return PendingIntent.getActivity(context,0,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    public boolean show(String tag,ComputerReminderDelivery.Event event){
        if(!allowed())return false;
        try{NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);
            manager.notify(tag,7101,new Notification.Builder(context,CHANNEL).setSmallIcon(R.drawable.ic_courseinbox_notification).setContentTitle(event.title).setContentText(event.body).setStyle(new Notification.BigTextStyle().bigText(event.body)).setContentIntent(history(context,tag)).setOnlyAlertOnce(true).setAutoCancel(true).setCategory(Notification.CATEGORY_REMINDER).setVisibility(Notification.VISIBILITY_PRIVATE).build());return true;
        }catch(RuntimeException error){return false;}
    }
    static Notification connection(Context context){
        Intent stop=new Intent(context,ComputerReminderService.class).setAction(ComputerReminderService.ACTION_STOP);
        PendingIntent action=PendingIntent.getService(context,0,stop,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(context,CONNECTION_CHANNEL).setSmallIcon(R.drawable.ic_courseinbox_notification).setContentTitle("正在接收电脑提醒").setContentText("同一 Wi-Fi · 点击查看连接与提醒历史").setContentIntent(history(context,"connection")).setOngoing(true).setOnlyAlertOnce(true).setCategory(Notification.CATEGORY_SERVICE).setVisibility(Notification.VISIBILITY_PRIVATE).addAction(new Notification.Action.Builder(null,"停止接收",action).build()).build();
    }
}
