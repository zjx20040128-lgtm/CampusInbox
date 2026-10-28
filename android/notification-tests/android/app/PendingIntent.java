package android.app;
import android.content.Context;
import android.content.Intent;
public class PendingIntent {
    public static final int FLAG_IMMUTABLE=1,FLAG_NO_CREATE=2,FLAG_UPDATE_CURRENT=4;
    private static PendingIntent current;
    public static PendingIntent getBroadcast(Context context,int code,Intent intent,int flags){
        if((flags&FLAG_NO_CREATE)!=0)return current;
        if(current==null)current=new PendingIntent();return current;
    }
    public void cancel(){current=null;}
}
