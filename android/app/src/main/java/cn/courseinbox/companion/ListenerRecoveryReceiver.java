package cn.courseinbox.companion;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Bounded recovery after upgrade/boot; never changes the user's listener grant. */
public final class ListenerRecoveryReceiver extends BroadcastReceiver {
    private static final String RETRY="cn.courseinbox.companion.RETRY_LISTENER";

    /** Also used when the app is opened with access granted but no listener callback. */
    public static void begin(Context context){recover(context,0);}

    @Override public void onReceive(Context context,Intent intent){
        if(intent==null)return;
        String action=intent.getAction();
        if(!Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)&&!Intent.ACTION_BOOT_COMPLETED.equals(action)&&!RETRY.equals(action))return;
        if(Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)||Intent.ACTION_BOOT_COMPLETED.equals(action)){
            NotificationQueue.preferences(context).edit().putInt("listener_rebind_count",0).putInt("listener_soft_reset_count",0).apply();
            ListenerDiagnostics.resetTiming(context);
        }
        ListenerDiagnostics.event(context,action);
        recover(context,RETRY.equals(action)?intent.getIntExtra("attempt",1):0);
    }

    private static PendingIntent intent(Context context,int attempt,int flags){
        Intent retry=new Intent(context,ListenerRecoveryReceiver.class).setAction(RETRY).putExtra("attempt",attempt);
        return PendingIntent.getBroadcast(context,0,retry,flags|PendingIntent.FLAG_IMMUTABLE);
    }

    private static void cancel(Context context){
        AlarmManager alarm=(AlarmManager)context.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pending=intent(context,0,PendingIntent.FLAG_NO_CREATE);
        if(alarm!=null&&pending!=null){alarm.cancel(pending);pending.cancel();}
    }

    private static void recover(Context context,int attempt){
        if(CourseNotificationService.isConnected()){cancel(context);return;}
        if(!CourseNotificationService.hasAccess(context)){
            ListenerDiagnostics.resetTiming(context);
            // Package replacement may briefly precede restored settings. Check once more.
            if(attempt==0)schedule(context,1);
            else {cancel(context);NotificationQueue.preferences(context).edit().putString("listener_status","系统通知使用权未开启，请在系统设置授权。").apply();}
            return;
        }
        boolean retryAvailable=ListenerRecoverySchedule.delayMillis(attempt)>=0;
        // Arm the next attempt before unbinding: Android may end the listener process.
        boolean armed=retryAvailable&&schedule(context,attempt+1);
        if(attempt<1||!armed||!CourseNotificationService.resetStaleBinding(context))CourseNotificationService.ensureConnected(context);
        if(!retryAvailable){
            cancel(context);
            NotificationQueue.preferences(context).edit().putString("listener_status","已授权，但 Android 仍未连接通知接收；请检查系统通知使用权与后台限制。").apply();
        }
    }

    /** A foreground reset must also have a durable retry armed before unbinding. */
    public static boolean armBindingResetFallback(Context context){return schedule(context,2);}

    private static boolean schedule(Context context,int nextAttempt){
        long delay=ListenerRecoverySchedule.delayMillis(nextAttempt-1);
        if(delay<0)return false;
        AlarmManager alarm=(AlarmManager)context.getSystemService(Context.ALARM_SERVICE);
        if(alarm==null){NotificationQueue.preferences(context).edit().putString("listener_status","系统无法安排通知接收重试，请打开应用再试。").apply();return false;}
        try{
            alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,System.currentTimeMillis()+delay,intent(context,nextAttempt,PendingIntent.FLAG_UPDATE_CURRENT));
            NotificationQueue.preferences(context).edit().putString("listener_status","通知使用权已开启；接收服务正在自动重连。").apply();
            return true;
        }catch(RuntimeException error){ListenerDiagnostics.error(context,"retry_schedule_failed",error);NotificationQueue.preferences(context).edit().putString("listener_status","系统未能安排通知接收重试，请打开应用再试。").apply();return false;}
    }
}
