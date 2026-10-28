package cn.courseinbox.companion;

/** Chooses text the posting app supplied in the expanded notification, when available. */
public final class NotificationText {
    private NotificationText() { }

    private static String clean(String value) { return value == null ? "" : value.trim(); }
    private static boolean isPrompt(String value) {
        return "请点击查看".equals(value) || "点击查看".equals(value) || "查看详情".equals(value);
    }

    public static String select(String plain, String big, String lines, String messages) {
        plain = clean(plain);
        big = clean(big);
        lines = clean(lines);
        messages = clean(messages);
        String best = "";
        for (String candidate : new String[] {messages, lines, big, plain}) {
            if (candidate.isEmpty()) continue;
            if (best.isEmpty() || (isPrompt(best) && !isPrompt(candidate)) ||
                isPrompt(best) == isPrompt(candidate) && candidate.length() > best.length()) best = candidate;
        }
        return best;
    }
}
