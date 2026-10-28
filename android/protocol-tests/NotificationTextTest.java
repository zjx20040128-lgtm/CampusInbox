import cn.courseinbox.companion.NotificationText;

public class NotificationTextTest {
    private static void check(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError("expected=" + expected + ", actual=" + actual);
    }

    public static void main(String[] args) {
        check("具体作业内容", NotificationText.select("请点击查看", "", "具体作业内容", ""));
        check("聊天正文", NotificationText.select("请点击查看", "", "", "聊天正文"));
        check("展开的详细内容", NotificationText.select("请点击查看", "展开的详细内容", "", ""));
        check("通知正文", NotificationText.select("通知正文", "摘要", "", ""));
        check("请点击查看", NotificationText.select("请点击查看", "", "", ""));
        check("完整的展开消息正文", NotificationText.select("请点击查看", "完整的展开消息正文", "", "请点击查看"));
        check("完整的多行消息正文", NotificationText.select("请点击查看", "", "完整的多行消息正文", "请点击查看"));
        System.out.println("Notification text selection: 7 assertions passed");
    }
}
