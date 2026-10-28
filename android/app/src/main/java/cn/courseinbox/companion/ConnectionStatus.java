package cn.courseinbox.companion;

/** Unknown transport outcomes must not look like normal sync progress. */
public final class ConnectionStatus {
    private ConnectionStatus() { }
    public static boolean failed(String status) {
        return !status.isEmpty()&&!status.startsWith("正在寻找并验证")&&!status.startsWith("已配对 ")
            &&!status.startsWith("新通知已排队")&&!status.startsWith("队列已发送完毕")
            &&!status.startsWith("发送成功")&&!status.startsWith("已手动清空待传队列")
            &&!status.startsWith("请先保存")&&!status.startsWith("尚未配对电脑");
    }
}
