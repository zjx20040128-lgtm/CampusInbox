import cn.courseinbox.companion.LocalInbox;
import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/** Exercises alert planning with persisted draft creation, not Android notification mocks. */
public final class MobileTaskAlertsTest {
    private static int assertions;
    private static void check(boolean ok,String reason){assertions++;if(!ok)throw new AssertionError(reason);}
    private static Object plan(List<LocalInbox.Task> before,LocalInbox inbox)throws Exception{
        return Class.forName("cn.courseinbox.companion.MobileTaskAlerts").getMethod("plan",List.class,List.class,List.class).invoke(null,before,inbox.tasks(),inbox.messages());
    }
    private static int count(Object batch)throws Exception{return batch.getClass().getField("count").getInt(batch);}
    public static void main(String[] args)throws Exception{
        boolean available=true;try{Class.forName("cn.courseinbox.companion.MobileTaskAlerts");}catch(ClassNotFoundException error){available=false;}
        check(available,"newly saved web tasks need a batch alert plan");
        File directory=Files.createTempDirectory("courseinbox-task-alert-test").toFile();
        try{
            LocalInbox inbox=new LocalInbox(new File(directory,"inbox.bin"));
            List<LocalInbox.Task> before=new ArrayList<>(inbox.tasks());
            LocalInbox.Message newest=new LocalInbox.Message("notice:new","学习通课程通知","测试","测试","学习通知","作业:《测试》作业20261015","作业:《测试》作业20261015\n请完成并提交作业。",1792063020000L,true,"https://notice.chaoxing.com/pc/notice/new/detail");
            LocalInbox.Message older=new LocalInbox.Message("notice:old","学习通课程通知","测试","测试","老师","第二次作业","第二次作业：提交报告。",1791976620000L,true,"https://notice.chaoxing.com/pc/notice/old/detail");
            inbox.ingest(newest);inbox.ingest(older);
            Object batch=plan(before,inbox);
            check(count(batch)==2,"several newly saved drafts form one batch result");
            check(((LocalInbox.Message)batch.getClass().getField("message").get(batch)).id.equals(newest.id),"batch alert opens the newest task's actual source");
            before=new ArrayList<>(inbox.tasks());
            check(!inbox.ingest(newest)&&!inbox.ingest(older),"replayed source messages remain deduplicated");
            check(count(plan(before,inbox))==0,"a repeated scan never alerts for existing drafts");
            inbox.ingest(new LocalInbox.Message("ordinary","学习通聊天","测试","测试","老师","教室变化","今晚改在另一间教室上课。",0,false,""));
            check(count(plan(before,inbox))==0,"ordinary saved messages do not create task alerts");
            check(inbox.tasks().stream().allMatch(task->task.status.equals("draft")),"an alert cannot confirm or submit tasks");
            java.lang.reflect.Method combine=null;
            try{combine=Class.forName("cn.courseinbox.companion.MobileTaskAlerts").getMethod("combine",batch.getClass(),batch.getClass());}catch(NoSuchMethodException ignored){}
            check(combine!=null,"one automatic notice pass combines batch plans into a single alert");
            before=new ArrayList<>(inbox.tasks());
            LocalInbox.Message later=new LocalInbox.Message("notice:later","学习通课程通知","测试","测试","老师","第三次作业","第三次作业：提交报告。",1792149420000L,true,"https://notice.chaoxing.com/pc/notice/later/detail");
            inbox.ingest(later);
            Object combined=combine.invoke(null,batch,plan(before,inbox));
            check(count(combined)==3,"the pass alert counts only drafts discovered by its constituent batches");
            check(((LocalInbox.Message)combined.getClass().getField("message").get(combined)).id.equals(later.id),"a combined pass alert opens its newest actual source");
            check(count(combine.invoke(null,combined,plan(inbox.tasks(),inbox)))==3,"a replayed batch cannot inflate the pass alert");
            Class<?> flowType=Class.forName("cn.courseinbox.companion.LearningReadFlow");
            java.lang.reflect.Method claim=null;try{claim=flowType.getMethod("claimAlert");}catch(NoSuchMethodException ignored){}
            check(claim!=null,"a dismissed pass notification must not be reposted by later batches");
            Object flow=flowType.getConstructor(String.class,boolean.class).newInstance("https://notice.chaoxing.com/pc/notice/myNotice",true);
            flowType.getMethod("record",int.class,int.class,int.class,int.class,int.class,int.class,batch.getClass()).invoke(flow,3,3,0,3,3,0,combined);
            check((Boolean)claim.invoke(flow)&&!(Boolean)claim.invoke(flow),"one saved pass may claim an alert only once regardless of shade dismissal");
        }finally{for(File file:directory.listFiles())file.delete();directory.delete();}
        System.out.println("Mobile task alert planning: "+assertions+" assertions passed");
    }
}
