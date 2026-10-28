package android.database.sqlite;
import android.content.Context;
public abstract class SQLiteOpenHelper {public SQLiteOpenHelper(Context context,String name,Object factory,int version){}public abstract void onCreate(SQLiteDatabase db);public abstract void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion);public SQLiteDatabase getReadableDatabase(){throw new UnsupportedOperationException();}public SQLiteDatabase getWritableDatabase(){throw new UnsupportedOperationException();}}
