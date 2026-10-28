package android.content;
public class Intent {
    public static final String ACTION_MY_PACKAGE_REPLACED="android.intent.action.MY_PACKAGE_REPLACED";
    public static final String ACTION_BOOT_COMPLETED="android.intent.action.BOOT_COMPLETED";
    private String action;private int attempt;
    public Intent(Context context,Class<?> receiver){}
    public Intent setAction(String value){action=value;return this;}
    public String getAction(){return action;}
    public Intent putExtra(String key,int value){attempt=value;return this;}
    public int getIntExtra(String key,int fallback){return attempt==0?fallback:attempt;}
}
