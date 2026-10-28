package android.app;
import android.service.notification.NotificationListenerService;
public class AlarmManager {
    public static final int RTC_WAKEUP=0;
    public static boolean rejectSchedule;
    public void setAndAllowWhileIdle(int type,long at,PendingIntent pending){if(rejectSchedule)throw new SecurityException("schedule denied");NotificationListenerService.events.add("schedule");}
    public void cancel(PendingIntent pending){NotificationListenerService.events.add("cancel");}
}
