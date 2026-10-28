package cn.courseinbox.companion;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.SystemClock;

/** Listener timing and a bounded lifecycle trace; never records notification contents. */
public final class ListenerDiagnostics {
    private static final long SLOW_AFTER_MS=180000L;
    private static final String START="listener_recovery_started_elapsed";
    private ListenerDiagnostics(){}

    public static void begin(Context context){
        SharedPreferences prefs=NotificationQueue.preferences(context);
        long now=SystemClock.elapsedRealtime(),start=prefs.getLong(START,-1);
        if(start<0||start>now){
            prefs.edit().putLong(START,now).apply();
            event(context,"recovery_start");
        }
    }

    public static void resetTiming(Context context){NotificationQueue.preferences(context).edit().putLong(START,-1).apply();}

    public static void connected(Context context){
        long elapsed=elapsedMillis(context);
        NotificationQueue.preferences(context).edit().putLong("listener_last_connect_duration_ms",elapsed).putLong(START,-1).apply();
        event(context,"listener_connected");
    }

    private static long elapsedMillis(Context context){
        long start=NotificationQueue.preferences(context).getLong(START,-1),now=SystemClock.elapsedRealtime();
        return start>=0&&now>=start?now-start:-1;
    }

    public static boolean shouldOfferHelp(Context context){
        return CourseNotificationService.hasAccess(context)&&!CourseNotificationService.isConnected()&&elapsedMillis(context)>=SLOW_AFTER_MS;
    }

    public static String status(Context context){
        if(CourseNotificationService.isConnected())return "接收正常";
        if(!CourseNotificationService.hasAccess(context))return "未开启";
        long elapsed=elapsedMillis(context);
        if(elapsed<0)return "等待系统连接";
        return (elapsed<SLOW_AFTER_MS?"正在连接":"连接较慢")+"（已等待 "+elapsed/1000+" 秒）";
    }

    public static synchronized void event(Context context,String event){
        SharedPreferences prefs=NotificationQueue.preferences(context);
        String log=prefs.getString("listener_event_log","");
        String[] lines=log.isEmpty()?new String[0]:log.split("\n");
        StringBuilder next=new StringBuilder();
        for(int i=Math.max(0,lines.length-23);i<lines.length;i++)next.append(lines[i]).append('\n');
        next.append(CourseNotificationService.timestamp(System.currentTimeMillis())).append(' ').append(event);
        prefs.edit().putString("listener_event_log",next.toString()).apply();
    }

    public static void error(Context context,String operation,RuntimeException error){
        String message=error.getMessage();
        if(message==null)message="";
        message=message.replace('\n',' ').replace('\r',' ');
        if(message.length()>200)message=message.substring(0,200);
        String detail=operation+": "+error.getClass().getSimpleName()+" "+message;
        NotificationQueue.preferences(context).edit().putString("listener_last_error",detail).apply();
        event(context,detail);
    }

    public static String report(Context context){
        SharedPreferences prefs=NotificationQueue.preferences(context);
        long duration=prefs.getLong("listener_last_connect_duration_ms",-1);
        return "通知使用权："+(CourseNotificationService.hasAccess(context)?"已开启":"未开启")
            +"\n接收状态："+status(context)
            +"\n当前服务："+CourseNotificationService.connectionStage()
            +"\n上次连接耗时："+(duration<0?"未记录":duration/1000+" 秒")
            +"\n重连请求："+prefs.getInt("listener_rebind_count",0)+" 次"
            +"\n绑定重建："+prefs.getInt("listener_soft_reset_count",0)+" 次"
            +"\n最近系统异常："+prefs.getString("listener_last_error","未记录")
            +"\n系统通知回调："+prefs.getInt("callback_count",0)+" 次；白名单匹配："+prefs.getInt("matched_count",0)+" 次"
            +"\n通知采集："+prefs.getString("capture_status","未记录")
            +"\n通知文字："+prefs.getString("text_field_status","未记录")
            +"\n通知栏补收："+prefs.getString("scan_status","未记录")
            +"\n其他通知包名："+prefs.getString("last_other_package","未记录")
            +"\n当前网页："+prefs.getString("web_reader_page","未记录")
            +"\n网页读取："+prefs.getString("web_reader_state","未记录")+"；上次来源列表 "+prefs.getInt("web_listed_count",0)+" 条，详情 "+prefs.getInt("web_detail_count",0)+" 条，失败 "+prefs.getInt("web_failed_count",0)+" 条"
            +"\n网页读取异常："+prefs.getString("web_reader_error","未记录")
            +"\n网页保存："+prefs.getString("web_capture_status","未记录")
            +"\n网页保存异常："+prefs.getString("web_save_error","未记录")
            +"\n课程通知同步："+prefs.getString("learning_sync_status","尚无读取记录")
            +"\n最近课程通知检查（UTC）："+(prefs.getLong("web_notice_checked_at",0)==0?"未记录":CourseNotificationService.timestamp(prefs.getLong("web_notice_checked_at",0)))
            +"\n最近课程通知保存："+prefs.getString("web_notice_capture_status","未记录")
            +"\n网页任务提醒："+prefs.getString("web_alert_status","未记录")
            +"\n服务事件（历史，UTC）：\n"+prefs.getString("listener_event_log","尚无记录");
    }
}
