package android.content;
public interface SharedPreferences {long getLong(String key,long fallback);boolean getBoolean(String key,boolean fallback);String getString(String key,String fallback);Editor edit();interface Editor {Editor putLong(String k,long v);Editor putBoolean(String k,boolean v);Editor putString(String k,String v);Editor remove(String k);boolean commit();}}
