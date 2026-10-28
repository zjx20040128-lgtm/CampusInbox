import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.service.notification.NotificationListenerService;
import cn.courseinbox.companion.CourseNotificationService;
import cn.courseinbox.companion.NotificationQueue;

/** Tests observable timing and diagnostic output from the real listener; no OEM claim. */
public final class ListenerDiagnosticsTest {
    private static int assertions;
    private static void check(boolean ok,String reason){assertions++;if(!ok)throw new AssertionError(reason);}
    private static Object diagnostic(String method,Context context)throws Exception{
        return Class.forName("cn.courseinbox.companion.ListenerDiagnostics").getMethod(method,Context.class).invoke(null,context);
    }
    public static void main(String[] args)throws Exception{
        Context context=new Context();
        CourseNotificationService service=new CourseNotificationService();
        service.onCreate();
        check(NotificationQueue.values.getOrDefault("listener_event_log","").toString().contains("service_create"),
            "diagnostics must reveal whether Android created the listener");
        service.onBind(new Intent(context,CourseNotificationService.class));
        check(diagnostic("report",context).toString().contains("已绑定"),"bound without a callback must remain distinguishable from connected");
        check(CourseNotificationService.ensureConnected(context),"authorized listener begins a timed recovery");
        SystemClock.now+=25000;
        check(!(boolean)diagnostic("shouldOfferHelp",context),"a 25-second wait must not be treated as a failed connection");
        check(diagnostic("status",context).toString().contains("正在连接"),"pending recovery must show progress rather than failure");
        check(CourseNotificationService.ensureConnected(context),"ordinary retries remain available while waiting");
        SystemClock.now+=125000;
        service.onListenerConnected();
        check(diagnostic("status",context).equals("接收正常"),"a delayed connection supersedes the waiting state");
        check(((Long)NotificationQueue.values.get("listener_last_connect_duration_ms"))==150000L,
            "connection duration starts at the first request, not the most recent retry");
        check(!(boolean)diagnostic("shouldOfferHelp",context),"connected listener must never show slow-connection help");
        service.onListenerDisconnected();
        SystemClock.now+=180000;
        check((boolean)diagnostic("shouldOfferHelp",context),"an unresolved three-minute wait should expose manual help");
        check(diagnostic("status",context).toString().contains("连接较慢"),"slow connection remains an unresolved state, not success");
        NotificationListenerService.rejectBind=true;
        CourseNotificationService.ensureConnected(context);
        String report=diagnostic("report",context).toString();
        check(report.contains("SecurityException")&&report.contains("denied"),"the actual system rejection must survive generic retry status updates");
        NotificationListenerService.rejectBind=false;
        service.onUnbind(new Intent(context,CourseNotificationService.class));
        service.onDestroy();
        report=diagnostic("report",context).toString();
        check(report.contains("当前没有接收服务实例"),"destroyed service must not appear bound in the current state");
        check(report.contains("service_bind")&&report.contains("service_unbind")&&report.contains("service_destroy"),"lifecycle events must survive for a phone-only diagnosis");
        Context.manager.access=false;
        check(diagnostic("status",context).equals("未开启"),"revoked access takes priority over old timing records");
        check(!(boolean)diagnostic("shouldOfferHelp",context),"revoked access must not produce slow-connection advice");
        System.out.println("PASS: listener timing/diagnostics: "+assertions+" assertions (Android boundary shim)");
    }
}
