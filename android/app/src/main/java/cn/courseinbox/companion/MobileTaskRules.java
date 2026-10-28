package cn.courseinbox.companion;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Conservative, on-device draft extraction. Nothing is submitted automatically. */
public final class MobileTaskRules {
    private static final ZoneOffset CN=ZoneOffset.ofHours(8);
    private static final Pattern COURSE=Pattern.compile("《([^》]{1,100})》");
    private static final Pattern DATE=Pattern.compile("(?:(\\d{4})[年/.-])?(\\d{1,2})[月/.-](\\d{1,2})[日号]?(?:\\s*(\\d{1,2})[:：时点](\\d{1,2})?分?)?");
    public static final class Candidate {
        public final String title,course,deadline,requirements,warning;
        Candidate(String title,String course,String deadline,String requirements,String warning){this.title=title;this.course=course;this.deadline=deadline;this.requirements=requirements;this.warning=warning;}
    }
    private MobileTaskRules(){}
    static boolean endedNotice(String text){return text!=null&&Pattern.compile("(?m)^\\s*(?:任务结束提醒|(?:本次|本项|该)?(?:作业|任务|考试)(?:已(?:经)?结束|已(?:经)?截止))(?:[\\s：:，,。；;！!]|$)").matcher(text).find();}
    public static Candidate extract(String text,long sourceTime,boolean timeKnown){
        if(text==null||text.trim().isEmpty()||endedNotice(text))return null;
        StringBuilder active=new StringBuilder();
        for(String clause:text.split("[。；;\\n]")){
            if(clause.matches(".*(?:无需|不需要|不用|暂时不|暂不|不要|取消|已完成|已经完成|已提交|已经提交).*"))continue;
            active.append(clause).append('。');
        }
        String value=active.toString();
        if(!Pattern.compile("作业|实验(?:报告|任务|\\d)|考试|(?:请|需要|务必).{0,12}(?:提交|完成|阅读|预习|讨论)|课前.{0,8}(?:阅读|预习|研讨|讨论)|准备.{0,8}(?:讨论|研讨|演讲|汇报)").matcher(value).find())return null;
        Matcher courseMatch=COURSE.matcher(text);String course=courseMatch.find()?courseMatch.group(1):"";
        String title=value.replaceFirst("《[^》]+》","").trim().replaceFirst("^(?:作业|考试|任务)\\s*[：:]\\s*","").split("[：:，,。\\n]",2)[0].trim();
        if(title.isEmpty())title="待核对学习任务";if(title.length()>100)title=title.substring(0,100);
        String deadline=deadline(value,sourceTime,timeKnown);
        String warning=deadline.isEmpty()?"截止时间尚未明确，请核对原文。":"";
        if(!timeKnown&&value.matches(".*(?:明天|后天|今天).*"))warning="消息发布时间未识别，不能推断相对截止日期。";
        if(value.contains("附件"))warning+=(warning.isEmpty()?"":" ")+"附件内容需在学习通核对。";
        return new Candidate(title,course,deadline,text,warning);
    }
    private static String deadline(String text,long sourceTime,boolean timeKnown){
        String context="";boolean revised=false;
        Matcher change=Pattern.compile("(?:(?:延期|延后|延长|推迟)(?:到|至)|截止(?:时间|日期)?(?:调整|更改|变更|改)(?:到|为|至))([^。；;，,\\n]{1,45})").matcher(text);
        while(change.find()){
            String prefix=text.substring(0,change.start()).replaceFirst("(?s).*[。；;，,\\n]","");
            if(Pattern.compile("未|不|申请|计划|拟|建议|取消").matcher(prefix).find())continue;
            context=change.group(1);revised=true;
        }
        if(!revised){
            Matcher cue=Pattern.compile("(?:截止|截至|最晚|结束时间|结束日期)([^。；;，,\\n]{0,45})").matcher(text);
            if(cue.find())context=cue.group(1);
            if(context.isEmpty()||(!DATE.matcher(context).find()&&!Pattern.compile("明天|后天|今天").matcher(context).find())){
                Matcher before=Pattern.compile("([^。；;，,\\n]{0,45})(?:截止|截至|前完成|前提交|上课前)").matcher(text);
                if(before.find())context=before.group(1);
            }
        }
        Matcher date=DATE.matcher(context);
        try {
            if(date.find()){
                if(date.group(1)==null&&!timeKnown)return "";
                int year=date.group(1)==null?Instant.ofEpochMilli(sourceTime).atOffset(CN).getYear():Integer.parseInt(date.group(1));
                LocalDate day=LocalDate.of(year,Integer.parseInt(date.group(2)),Integer.parseInt(date.group(3)));
                if(date.group(4)==null)return day.toString();
                LocalTime time=LocalTime.of(Integer.parseInt(date.group(4)),date.group(5)==null?0:Integer.parseInt(date.group(5)));
                return day.atTime(time).atOffset(CN).format(DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ssXXX"));
            }
            if(timeKnown&&(revised||Pattern.compile("截止|截至|结束时间|结束日期|上课前|前完成|前提交").matcher(text).find())){
                int days=context.contains("后天")?2:context.contains("明天")?1:context.contains("今天")?0:-1;
                if(days>=0)return Instant.ofEpochMilli(sourceTime).atOffset(CN).toLocalDate().plusDays(days).toString();
            }
        }catch(RuntimeException ignored){return "";}
        return "";
    }
    public static boolean validDeadline(String value){
        if(value==null||value.isEmpty())return true;
        try{if(value.matches("\\d{4}-\\d{2}-\\d{2}"))LocalDate.parse(value);else OffsetDateTime.parse(value);return true;}
        catch(RuntimeException ignored){return false;}
    }
    public static boolean overdue(String deadline,String status,long now){
        if(deadline==null||deadline.isEmpty()||status.equals("submitted")||status.equals("cancelled")||status.equals("draft")||status.equals("ignored"))return false;
        try {
            if(deadline.matches("\\d{4}-\\d{2}-\\d{2}"))return Instant.ofEpochMilli(now).atOffset(CN).toLocalDate().isAfter(LocalDate.parse(deadline));
            return Instant.ofEpochMilli(now).isAfter(OffsetDateTime.parse(deadline).toInstant());
        }catch(RuntimeException ignored){return false;}
    }
    public static String statusLabel(String status){
        switch(status){case "draft":return "待确认";case "pending":return "待开始";case "in_progress":return "进行中";case "done":return "已做完";case "submitted":return "已提交";case "cancelled":return "已取消";case "ignored":return "已忽略";default:return "需核对";}
    }
    public static String displayStatus(String deadline,String status,long now){return overdue(deadline,status,now)?"已逾期（未提交）":statusLabel(status);}
}
