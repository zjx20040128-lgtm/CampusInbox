package cn.courseinbox.companion;

import java.net.URI;
import java.util.UUID;

/** Resumes a requested source after login and totals a bounded foreground notice pass. */
public final class LearningReadFlow {
    private final String target;
    private final boolean automatic;
    private boolean routed;
    private boolean awaiting,saving;
    private long readId;
    private boolean alertAttempted,alertRequested;
    private final String alertKey=UUID.randomUUID().toString();
    private MobileTaskAlerts.Batch alerts;
    private int expected=-1,inspected,saved,drafts,unread,failed;
    public LearningReadFlow(String requestedUrl,boolean returnToInbox){
        target=LearningUrls.collectible(requestedUrl)?requestedUrl:"";
        automatic=returnToInbox&&LearningUrls.NOTICES.equals(target);
    }
    public synchronized String nextPage(String currentUrl,String state,boolean authenticated){
        if(!authenticated||!"authenticated".equals(state)||!portal(currentUrl)||target.isEmpty()||routed)return "";
        routed=true;return target;
    }
    private static boolean portal(String value){
        if(!LearningUrls.allowed(value))return false;
        try{
            URI uri=new URI(value);String path=uri.getPath();
            return (uri.getHost().equals("i.chaoxing.com")&&(path.equals("/")||path.equals("/base")||path.equals("/base/")))
                ||(uri.getHost().equals("mooc2-ans.chaoxing.com")&&path.equals("/visit/interaction"));
        }catch(Exception ignored){return false;}
    }
    public static String pageLabel(String value){
        if(!LearningUrls.allowed(value))return "不受支持的页面";
        if(LearningUrls.login(value))return "官方登录页";
        if(LearningUrls.collectible(value))return value.startsWith("https://notice.chaoxing.com/")?"课程通知":"聊天消息";
        return portal(value)?"登录后门户":"其他官方页面";
    }
    public boolean isAutomatic(){return automatic;}
    public String targetUrl(){return target;}
    public synchronized LearningReadFlow forPage(){LearningReadFlow result=new LearningReadFlow(target,automatic);result.routed=routed;return result;}
    public synchronized long startRead(){awaiting=true;return ++readId;}
    public synchronized long currentRead(){return readId;}
    public synchronized boolean awaitingSnapshot(){return awaiting;}
    public synchronized boolean consumeRead(long id){if(!awaiting||id!=readId)return false;awaiting=false;return true;}
    public synchronized void startSaving(){saving=true;}
    public synchronized void finishSaving(){saving=false;}
    public synchronized boolean saving(){return saving;}
    public synchronized int nextNoticeLimit(){return automatic&&expected>=0?Math.min(5,Math.max(0,expected-inspected)):5;}
    public synchronized void record(int listed,int checked,int readFailed,int added,int discovered,int saveFailed){record(listed,checked,readFailed,added,discovered,saveFailed,null);}
    public synchronized void record(int listed,int checked,int readFailed,int added,int discovered,int saveFailed,MobileTaskAlerts.Batch batch){
        expected=Math.max(expected,Math.min(100,Math.max(0,listed)));
        inspected=Math.min(expected,inspected+Math.max(0,checked));
        saved+=Math.max(0,added);drafts+=Math.max(0,discovered);unread+=Math.max(0,readFailed);failed+=Math.max(0,saveFailed);
        alerts=MobileTaskAlerts.combine(alerts,batch);
    }
    public synchronized MobileTaskAlerts.Batch alertPlan(){return MobileTaskAlerts.combine(alerts,null);}
    public synchronized boolean claimAlert(){if(alertAttempted||alertPlan().count==0)return false;alertAttempted=true;return true;}
    public synchronized void alertResult(boolean requested){alertRequested|=requested;}
    public synchronized boolean alertRequested(){return alertRequested;}
    public String alertKey(){return alertKey;}
    public synchronized boolean hasMore(){return automatic&&expected>=0&&inspected<expected;}
    public synchronized boolean shouldReturn(String currentUrl){return automatic&&LearningUrls.NOTICES.equals(currentUrl)&&expected>=0&&inspected>=expected;}
    public synchronized String summary(){return "本轮检查 "+inspected+" 条；保存 "+saved+" 条；新增 "+drafts+" 项任务；未读 "+unread+" 条；保存失败 "+failed+" 条。";}
}
