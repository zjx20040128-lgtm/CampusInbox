import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.service.notification.NotificationListenerService;
import cn.courseinbox.companion.CourseNotificationService;
import cn.courseinbox.companion.ListenerRecoveryReceiver;
import cn.courseinbox.companion.NotificationQueue;
import java.util.List;

/** Checks upgrade recovery order at the Android API boundary; no device claim. */
public final class ListenerUpgradeRecoveryTest {
    private static void check(boolean good,String reason){if(!good)throw new AssertionError(reason);}
    public static void main(String[] args){
        Context context=new Context();ListenerRecoveryReceiver receiver=new ListenerRecoveryReceiver();
        receiver.onReceive(context,new Intent(context,ListenerRecoveryReceiver.class).setAction(Intent.ACTION_MY_PACKAGE_REPLACED));
        check(NotificationListenerService.binds==1&&NotificationListenerService.unbinds==0,"upgrade first requests an ordinary bind");
        check(NotificationQueue.values.get("listener_soft_reset_count").equals(0),"upgrade resets the one-shot recovery state");
        SystemClock.now+=15000;
        NotificationListenerService.events.clear();
        receiver.onReceive(context,new Intent(context,ListenerRecoveryReceiver.class).setAction("cn.courseinbox.companion.RETRY_LISTENER").putExtra("attempt",1));
        List<String> events=NotificationListenerService.events;
        check(events.indexOf("schedule")>=0&&events.indexOf("schedule")<events.indexOf("unbind"),"fallback alarm must be armed before unbinding can end the process");
        check(events.indexOf("commit")>=0&&events.indexOf("commit")<events.indexOf("unbind"),"one-shot reset state must reach disk before unbinding can end the process");
        check(NotificationListenerService.unbinds==1&&NotificationListenerService.binds==2,"first retry rebuilds the stale binding once");
        check(NotificationQueue.values.get("listener_soft_reset_count").equals(1),"successful reset is persisted as one shot");
        new CourseNotificationService().onListenerConnected();
        receiver.onReceive(context,new Intent(context,ListenerRecoveryReceiver.class).setAction("cn.courseinbox.companion.RETRY_LISTENER").putExtra("attempt",2));
        check(NotificationListenerService.unbinds==1,"connected listener is never unbound by a late alarm");
        System.out.println("PASS: upgrade recovery alarm precedes binding reset");
    }
}
