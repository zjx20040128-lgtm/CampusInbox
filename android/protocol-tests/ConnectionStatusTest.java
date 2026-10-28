import cn.courseinbox.companion.ConnectionStatus;
public class ConnectionStatusTest {
    public static void main(String[] args) {
        String[] errors={
            "未找到已配对电脑；请确认电脑已启动，或使用当前地址手动连接。",
            "请连接与电脑相同的 Wi-Fi，再寻找电脑。",
            "此手机的网络发现服务不可用，请手动连接。",
            "无法启动网络发现，请手动连接。",
            "服务器拒绝 HTTP 401；事件仍在队列，请检查令牌、白名单和时间。",
            "unexpected network response"
        };
        for(String error:errors)if(!ConnectionStatus.failed(error))throw new AssertionError("Failure hidden: "+error);
        String[] normal={"","正在寻找并验证电脑…","已配对 CourseInbox-1234abcd；连接地址已自动更新。","队列已发送完毕。","新通知已排队，等待发送。","发送成功，剩余 1 条。","已手动清空待传队列。","请先保存服务地址和令牌。","尚未配对电脑，请点击自动寻找并配对。"};
        for(String status:normal)if(ConnectionStatus.failed(status))throw new AssertionError("Normal progress treated as failure: "+status);
        System.out.println("Connection status: 15 assertions passed");
    }
}
