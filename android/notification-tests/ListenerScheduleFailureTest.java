import android.app.AlarmManager;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.service.notification.NotificationListenerService;
import cn.courseinbox.companion.ListenerRecoveryReceiver;

/** A failed alarm must not leave an authorized listener intentionally unbound. */
public final class ListenerScheduleFailureTest {
    private static void check(boolean good,String reason){if(!good)throw new AssertionError(reason);}
    public static void main(String[] args){
        Context context=new Context();ListenerRecoveryReceiver receiver=new ListenerRecoveryReceiver();
        AlarmManager.rejectSchedule=true;
        receiver.onReceive(context,new Intent(context,ListenerRecoveryReceiver.class).setAction(Intent.ACTION_MY_PACKAGE_REPLACED));
        SystemClock.now+=15000;
        receiver.onReceive(context,new Intent(context,ListenerRecoveryReceiver.class).setAction("cn.courseinbox.companion.RETRY_LISTENER").putExtra("attempt",1));
        check(NotificationListenerService.unbinds==0,"without a fallback alarm, recovery must not unbind the listener");
        check(NotificationListenerService.binds>=1,"ordinary rebind remains available when scheduling fails");
        System.out.println("PASS: failed alarm keeps non-destructive rebind path");
    }
}
