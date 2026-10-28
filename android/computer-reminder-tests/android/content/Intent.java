package android.content;
import android.net.Uri;
public class Intent {public static final int FLAG_ACTIVITY_CLEAR_TOP=0x04000000,FLAG_ACTIVITY_SINGLE_TOP=0x20000000;public final Class<?> target;public String action;public Uri data;public int flags;public Intent(Context c,Class<?> target){this.target=target;}public Intent setAction(String action){this.action=action;return this;}public Intent setData(Uri data){this.data=data;return this;}public Intent addFlags(int flags){this.flags|=flags;return this;}}
