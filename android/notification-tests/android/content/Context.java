package android.content;
import android.app.NotificationManager;
import android.app.AlarmManager;
public class Context {
    public static final String NOTIFICATION_SERVICE="notification";
    public static final String ALARM_SERVICE="alarm";
    public static final NotificationManager manager=new NotificationManager();
    public static final AlarmManager alarm=new AlarmManager();
    public Context getApplicationContext(){return this;}
    public String getPackageName(){return "cn.courseinbox.companion";}
    public Object getSystemService(String name){return ALARM_SERVICE.equals(name)?alarm:manager;}
    public Object getContentResolver(){return null;}
}
