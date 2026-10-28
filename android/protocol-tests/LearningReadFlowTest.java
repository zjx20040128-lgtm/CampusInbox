import cn.courseinbox.companion.LearningUrls;

/** Regression for login-only pages being mistaken for completed source collection. */
public final class LearningReadFlowTest {
    private static int assertions;
    private static Class<?> type;
    private static void check(boolean ok,String reason){assertions++;if(!ok)throw new AssertionError(reason);}
    private static Object flow(String url,boolean back)throws Exception{return type.getConstructor(String.class,boolean.class).newInstance(url,back);}
    private static String next(Object flow,String url,String state,boolean authenticated)throws Exception{return (String)type.getMethod("nextPage",String.class,String.class,boolean.class).invoke(flow,url,state,authenticated);}
    private static void batch(Object flow,int listed,int inspected,int unread,int saved,int drafts,int errors)throws Exception{type.getMethod("record",int.class,int.class,int.class,int.class,int.class,int.class).invoke(flow,listed,inspected,unread,saved,drafts,errors);}
    private static boolean more(Object flow)throws Exception{return (Boolean)type.getMethod("hasMore").invoke(flow);}
    private static boolean back(Object flow,String url)throws Exception{return (Boolean)type.getMethod("shouldReturn",String.class).invoke(flow,url);}
    private static String summary(Object flow)throws Exception{return (String)type.getMethod("summary").invoke(flow);}
    public static void main(String[] args)throws Exception{
        try{type=Class.forName("cn.courseinbox.companion.LearningReadFlow");}catch(ClassNotFoundException ignored){}
        check(type!=null,"a requested notice refresh must continue beyond portal authentication");
        Object notices=flow(LearningUrls.NOTICES,true);
        check(next(notices,"https://i.chaoxing.com/base","authenticated",false).isEmpty(),"unverified login cannot navigate into collection");
        check(!back(notices,LearningUrls.NOTICES),"logging in alone never completes a refresh");
        check(next(notices,"https://i.chaoxing.com/base","authenticated",true).equals(LearningUrls.NOTICES),"login redirects back to the originally requested notices");
        check(next(notices,"https://i.chaoxing.com/base","authenticated",true).isEmpty(),"a rejected source cannot create an automatic redirect loop");
        check(next(flow(LearningUrls.CHAT,false),"https://mooc2-ans.chaoxing.com/visit/interaction","authenticated",true).equals(LearningUrls.CHAT),"chat requests also resume after official login");
        check(next(flow(LearningUrls.PORTAL,false),"https://i.chaoxing.com/base","authenticated",true).isEmpty(),"opening the official portal for browsing keeps that page");
        for(String bad:new String[]{"https://i.chaoxing.com.evil.example/base","http://i.chaoxing.com/base","https://i.chaoxing.com/unknown"})check(next(flow(LearningUrls.NOTICES,true),bad,"authenticated",true).isEmpty(),"unrecognized login evidence cannot redirect: "+bad);
        batch(notices,13,5,0,5,4,0);
        check(more(notices)&&!back(notices,LearningUrls.NOTICES),"five of thirteen inspected notices must not return before the remaining batches");
        batch(notices,13,5,0,5,2,0);
        java.lang.reflect.Method limit=null;try{limit=type.getMethod("nextNoticeLimit");}catch(NoSuchMethodException ignored){}
        check(limit!=null,"the last automatic batch must request only the remaining notices");
        check((Integer)limit.invoke(notices)==3,"thirteen notices leave three after two batches");
        batch(notices,13,3,0,3,0,0);
        check(!more(notices)&&back(notices,LearningUrls.NOTICES),"a fully persisted notice pass returns to the inbox");
        check(!back(notices,LearningUrls.CHAT),"a stale notice result cannot close a different source page");
        check(summary(notices).contains("保存 13 条")&&summary(notices).contains("新增 6 项"),"the displayed result totals actual persistence across batches");
        Object manual=flow(LearningUrls.NOTICES,false);batch(manual,13,5,0,5,1,0);
        check(!more(manual)&&!back(manual,LearningUrls.NOTICES),"manual source browsing remains open");
        Object empty=flow(LearningUrls.NOTICES,true);batch(empty,0,0,0,0,0,0);
        check(back(empty,LearningUrls.NOTICES),"a recognized empty notice list can complete without inventing tasks");
        Object partial=flow(LearningUrls.NOTICES,true);batch(partial,5,5,2,3,1,0);
        check(back(partial,LearningUrls.NOTICES)&&summary(partial).contains("未读 2 条"),"read failures survive the return to the inbox");
        Object failedSave=flow(LearningUrls.NOTICES,true);batch(failedSave,1,1,0,0,0,1);
        check(summary(failedSave).contains("保存失败 1 条"),"storage failures cannot be reported as successful task creation");
        Object fresh=type.getMethod("forPage").invoke(notices);
        check(!back(fresh,LearningUrls.NOTICES),"a new page load receives an independent unfinished pass");
        batch(notices,13,1,0,1,1,0);
        check(summary(fresh).contains("保存 0 条")&&!back(fresh,LearningUrls.NOTICES),"a late saved result belongs to its old page rather than the current page");
        check(next(fresh,"https://i.chaoxing.com/base","authenticated",true).isEmpty(),"new page identity preserves the anti-redirect-loop guard");
        Object pending=flow(LearningUrls.NOTICES,true);
        Object request=type.getMethod("startRead").invoke(pending);
        check((Boolean)type.getMethod("awaitingSnapshot").invoke(pending),"a paused read remains pending for resume instead of being overwritten");
        java.lang.reflect.Method consume=null;try{consume=type.getMethod("consumeRead",long.class);}catch(NoSuchMethodException ignored){}
        check(consume!=null,"a pending snapshot can be consumed only once even when callbacks overlap");
        long requestId=(Long)request;
        check((Boolean)consume.invoke(pending,requestId)&&!(Boolean)consume.invoke(pending,requestId),"overlapping callbacks cannot save or count the same snapshot twice");
        type.getMethod("startSaving").invoke(pending);
        check((Boolean)type.getMethod("saving").invoke(pending),"an in-flight save blocks starting another poll");
        batch(pending,5,5,0,5,2,0);
        check((Boolean)type.getMethod("saving").invoke(pending)&&summary(pending).contains("新增 2 项"),"accounting a saved batch does not release the poll before post-save work ends");
        type.getMethod("finishSaving").invoke(pending);
        check(!(Boolean)type.getMethod("saving").invoke(pending),"the next poll starts only after all save-side effects finish");
        long newer=(Long)type.getMethod("startRead").invoke(pending);
        check(!(Boolean)consume.invoke(pending,requestId)&&(Boolean)consume.invoke(pending,newer),"an old result cannot consume the newer pending read");
        Object bounded=flow(LearningUrls.NOTICES,true);
        for(int i=0;i<20;i++)batch(bounded,180,5,0,5,0,0);
        check(!more(bounded)&&back(bounded,LearningUrls.NOTICES),"automatic reading has a bounded hundred-notice pass");
        System.out.println("Learning source flow: "+assertions+" assertions passed");
    }
}
