package android.database;
public interface Cursor extends AutoCloseable {boolean moveToFirst();boolean moveToNext();String getString(int index);long getLong(int index);void close();}
