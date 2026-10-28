import cn.courseinbox.companion.LocalInbox;
import cn.courseinbox.companion.MobileTaskRules;
import cn.courseinbox.companion.LearningUrls;
import cn.courseinbox.companion.PendingNotificationStore;
import java.io.File;
import java.nio.file.Files;
import java.time.Instant;
import java.time.Clock;
import java.time.ZoneOffset;
import java.util.List;

public final class MobileInboxTest {
    private static int assertions;
    private static void check(boolean condition,String message){assertions++;if(!condition)throw new AssertionError(message);}
    private static long stamp(String value){return Instant.parse(value).toEpochMilli();}
    public static void main(String[] args)throws Exception {
        long now=stamp("2026-10-10T08:00:00Z");
        MobileTaskRules.Candidate task=MobileTaskRules.extract("《软件工程》第三次作业：请提交实验报告、源代码。截止：2026年10月12日20:00。",now,true);
        check(task!=null,"assignment produces a draft");
        check(task.course.equals("软件工程"),"course kept");
        check(task.deadline.equals("2026-10-12T20:00:00+08:00"),"explicit deadline preserved");
        check(task.title.contains("第三次作业"),"task title preserved");
        MobileTaskRules.Candidate published=MobileTaskRules.extract("作业:《测试》作业20261015\n老师发布了新的作业，请完成并提交。",now,true);
        check(published!=null&&published.title.equals("作业20261015"),"a published work notice keeps the actual work name after its generic prefix");
        check(published.course.equals("测试")&&published.deadline.isEmpty(),"a task number is not evidence of a deadline");
        MobileTaskRules.Candidate timed=MobileTaskRules.extract("作业:《测试》作业20261015\n课程名称：测试\n作业名称：作业20261015\n开始时间：2026-10-15 19:16\n结束时间：2026-10-21 21:16",now,true);
        check(timed!=null&&timed.deadline.equals("2026-10-21T21:16:00+08:00"),"an official work end time is the deadline rather than its start time");
        check(MobileTaskRules.extract("作业:《测试》作业20261015\n开始时间：2026-10-15 19:16",now,true).deadline.isEmpty(),"a start time alone is not a deadline");
        check(MobileTaskRules.extract("今晚有班级活动，请关注",now,true)==null,"ordinary notice is not a task");
        check(MobileTaskRules.extract("请点击查看",now,true)==null,"notification prompt is not a task");
        check(MobileTaskRules.extract("不需要提交作业，暂时不用阅读",now,true)==null,"negated instruction is not a task");
        check(MobileTaskRules.extract("第三次作业已经提交",now,true)==null,"completed action is not a task");
        check(MobileTaskRules.extract("《英语》课前阅读第3章，明天上课前完成",now,true).deadline.equals("2026-10-11"),"relative deadline uses source time");
        check(MobileTaskRules.extract("请提交实验报告，明天截止",now,false).deadline.isEmpty(),"unknown source time cannot invent relative date");
        check(MobileTaskRules.extract("第三次作业截止10月32日",now,true).deadline.isEmpty(),"invalid date is not normalized");
        check(MobileTaskRules.extract("明天讲解第三次作业，今天截止",now,true).deadline.equals("2026-10-10"),"relative date must belong to the deadline clause");
        check(MobileTaskRules.extract("第三次作业，截止2026.10.12 20:00",now,true).deadline.equals("2026-10-12T20:00:00+08:00"),"dotted explicit date is supported");
        check(!MobileTaskRules.overdue("2026-10-10","pending",now),"date-only deadline valid all day");
        check(MobileTaskRules.overdue("2026-10-09","pending",now),"previous day deadline overdue");
        check(!MobileTaskRules.overdue("2026-10-09","submitted",now),"submitted not overdue");
        check(MobileTaskRules.overdue("2026-10-09","done",now),"done is not submitted");
        check(MobileTaskRules.displayStatus("2026-10-09","pending",now).equals("已逾期（未提交）"),"overdue task is not displayed as pending");
        check(MobileTaskRules.displayStatus("2026-10-09","submitted",now).equals("已提交"),"submitted status remains visible after deadline");

        File directory=Files.createTempDirectory("courseinbox-mobile-test").toFile();
        File data=new File(directory,"inbox.bin");
        try {
            Clock clock=Clock.fixed(Instant.ofEpochMilli(now),ZoneOffset.UTC);
            LocalInbox inbox=new LocalInbox(data,clock);
            LocalInbox.Message m=new LocalInbox.Message("chat:123","学习通聊天","课程群",task.course,"老师","第三次作业", "《软件工程》第三次作业：提交实验报告，截止2026年10月12日20:00",now,true,"https://fe.chaoxing.com/front/webim/index.html");
            check(inbox.ingest(m),"message saved");
            check(!inbox.ingest(m),"stable replay deduplicated");
            check(inbox.messages().size()==1,"original stored once");
            check(inbox.tasks().size()==1&&inbox.tasks().get(0).status.equals("draft"),"intake creates draft only");
            String id=inbox.tasks().get(0).id;
            inbox.confirm(id,"第三次作业","软件工程","2026-10-12T20:00:00+08:00");
            check(inbox.tasks().get(0).status.equals("pending"),"human confirmation creates pending task");
            inbox.setStatus(id,"submitted");
            LocalInbox reopened=new LocalInbox(data,clock);
            check(reopened.tasks().get(0).status.equals("submitted"),"task status persists after restart");
            check(reopened.messages().get(0).text.equals(m.text),"source evidence persists exactly");
            check(reopened.tasks().get(0).messageId.equals(reopened.messages().get(0).id),"task links original evidence");
            boolean rejected=false;try{reopened.setStatus(id,"auto-submitted");}catch(IllegalArgumentException expected){rejected=true;}
            check(rejected,"unknown status rejected");
            rejected=false;try{reopened.confirm(id,"任务","课程","2026-02-30");}catch(IllegalArgumentException expected){rejected=true;}
            check(rejected,"invalid edited deadline rejected");
            reopened.ingest(new LocalInbox.Message("notice:summary","系统通知","学习通","","","学习通","您有一条新消息，请点击查看",now,true,""));
            check(reopened.messages().size()==2,"summary retained as message");
            check(reopened.tasks().size()==1,"summary creates no draft");
            Files.write(data.toPath(),new byte[]{1,2,3});
            rejected=false;try{new LocalInbox(data);}catch(java.io.IOException expected){rejected=true;}
            check(rejected,"corrupt archive must not silently reset");
        } finally {for(File file:directory.listFiles())file.delete();directory.delete();}
        File pendingDir=Files.createTempDirectory("courseinbox-notification-retry").toFile();
        try {
            PendingNotificationStore pending=new PendingNotificationStore(pendingDir);
            pending.enqueue("original-notification");pending.enqueue("original-notification");
            check(pending.entries().size()==1,"incoming notification replay is deduplicated");
            pending=new PendingNotificationStore(pendingDir);
            check(pending.entries().get(0).payload.equals("original-notification"),"failed inbox writes survive restart in pending spool");
            String id=pending.entries().get(0).id;
            check(pending.entries().size()==1,"reading does not acknowledge evidence");
            pending.acknowledge(id);
            check(pending.entries().isEmpty(),"explicit success removes only acknowledged notification");
            boolean rejected=false;try{pending.acknowledge("../outside");}catch(IllegalArgumentException expected){rejected=true;}
            check(rejected,"queue acknowledgements cannot leave private directory");
            File blocked=new File(pendingDir,"blocked");Files.write(blocked.toPath(),new byte[]{1});
            rejected=false;try{new PendingNotificationStore(blocked).enqueue("new-message");}catch(java.io.IOException expected){rejected=true;}
            check(rejected,"failed queue writes are explicit");
            pending.enqueue("invalid-notification");pending.enqueue("valid-notification");
            PendingNotificationStore.DrainResult result=pending.drain(entry->{
                if(entry.payload.equals("invalid-notification"))throw new IllegalArgumentException("invalid payload");
            });
            check(result.saved==1&&result.pending==1,"one bad notification does not block later valid evidence");
            check(pending.entries().get(0).payload.equals("invalid-notification"),"invalid evidence remains available for retry");
            check(!result.error.isEmpty(),"single-notification failures remain visible");
            pending.enqueue("storage-failed");
            result=pending.drain(entry->{throw new java.io.IOException("disk unavailable");});
            check(result.saved==0&&result.pending==2,"storage failure retains every unacknowledged notification");
            result=pending.drain(entry->{});
            check(result.saved==2&&result.pending==0,"recovered writes clear only successfully saved evidence");
        } finally {for(File file:pendingDir.listFiles())file.delete();pendingDir.delete();}
        check(LearningUrls.allowed("https://passport2.chaoxing.com/login"),"official login allowed");
        check(LearningUrls.login("https://passport2.chaoxing.com/login?newversion=true"),"login styling stays on the official authentication entry");
        check(!LearningUrls.login("https://fe.chaoxing.com/front/webim/index.html"),"chat pages do not receive login styling");
        check(!LearningUrls.login("https://passport2.chaoxing.com/login-other"),"unknown login variants keep their original layout");
        check(!LearningUrls.allowed("http://i.chaoxing.com"),"insecure login rejected");
        check(!LearningUrls.allowed("https://chaoxing.com.evil.example/login"),"lookalike domain rejected");
        check(!LearningUrls.allowed("https://user:pass@i.chaoxing.com"),"embedded credentials rejected");
        check(!LearningUrls.allowed("file:///sdcard/test.html"),"local script source rejected");
        check(LearningUrls.collectible("https://fe.chaoxing.com/front/webim/index.html"),"chat collector allowed");
        check(!LearningUrls.collectible("https://passport2.chaoxing.com/login"),"login form not a message source");
        System.out.println("Mobile standalone inbox: "+assertions+" assertions passed");
    }
}
