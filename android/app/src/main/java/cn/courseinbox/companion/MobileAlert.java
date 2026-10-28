package cn.courseinbox.companion;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;

/** Shows a phone-local alert only after a new Learning notification is saved. */
public final class MobileAlert {
    private static final String CHANNEL="learning_messages";
    private MobileAlert(){}

    public static boolean canShow(Context context){
        if(Build.VERSION.SDK_INT>=33&&context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return false;
        NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);
        if(manager==null||!manager.areNotificationsEnabled())return false;
        NotificationChannel channel=manager.getNotificationChannel(CHANNEL);
        return channel==null||channel.getImportance()!=NotificationManager.IMPORTANCE_NONE;
    }

    public static boolean show(Context context,LocalInbox.Message message){
        return show(context,message,message.title.isEmpty()?"学习通新消息":message.title);
    }
    public static boolean showTasks(Context context,MobileTaskAlerts.Batch batch){
        return batch.count>0&&batch.message!=null&&show(context,batch.message,"发现 "+batch.count+" 项学习任务，待确认");
    }
    public static boolean showTasks(Context context,MobileTaskAlerts.Batch batch,String passKey){
        return batch.count>0&&batch.message!=null&&show(context,batch.message,"发现新的学习任务，待确认","read-pass:"+passKey,true);
    }
    private static boolean show(Context context,LocalInbox.Message message,String heading){
        return show(context,message,heading,"message:"+message.id,false);
    }
    private static boolean show(Context context,LocalInbox.Message message,String heading,String tag,boolean onlyOnce){
        if(!canShow(context))return false;
        try{
            NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel channel=new NotificationChannel(CHANNEL,"学习通消息提醒",NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("收到学习通通知或网页读取发现新任务后，提醒并打开消息原文");
            manager.createNotificationChannel(channel);
            Intent open=new Intent(context,MainActivity.class)
                .setAction("cn.courseinbox.companion.OPEN_MESSAGE")
                .setData(Uri.parse("courseinbox://message/"+message.id))
                .putExtra(MainActivity.EXTRA_MESSAGE_ID,message.id)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent tap=PendingIntent.getActivity(context,0,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
            String body=message.text.trim();
            String preview=body.replace('\n',' ');
            if(preview.length()>180)preview=preview.substring(0,180)+"…";
            Notification alert=new Notification.Builder(context,CHANNEL)
                .setSmallIcon(R.drawable.ic_courseinbox_notification)
                .setContentTitle(heading)
                .setContentText(preview)
                .setStyle(new Notification.BigTextStyle().bigText(body.length()>1000?body.substring(0,1000)+"…":body))
                .setContentIntent(tap)
                .setAutoCancel(true)
                .setOnlyAlertOnce(onlyOnce)
                .setCategory(Notification.CATEGORY_MESSAGE)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .build();
            manager.notify(tag,1,alert);
            return true;
        }catch(RuntimeException error){return false;}
    }
}
