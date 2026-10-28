package android.content;
public final class ComponentName {
    private final String name;
    public ComponentName(Context context,Class<?> type){name=context.getPackageName()+"/"+type.getName();}
    private ComponentName(String value){name=value;}
    public static ComponentName unflattenFromString(String value){int slash=value.indexOf('/');if(slash<0)return null;String type=value.substring(slash+1);return new ComponentName(value.substring(0,slash+1)+(type.startsWith(".")?value.substring(0,slash)+type:type));}
    public String flattenToString(){return name;}
    @Override public boolean equals(Object value){return value instanceof ComponentName&&name.equals(((ComponentName)value).name);}
    @Override public int hashCode(){return name.hashCode();}
}
