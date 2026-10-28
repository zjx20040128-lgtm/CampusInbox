package cn.courseinbox.companion;

import java.net.URI;

/** Literal RFC1918 IPv4 only: never DNS, public hosts, userinfo or paths. */
public final class ComputerReminderProtocol {
    private ComputerReminderProtocol() {}
    public static String endpoint(String value) {
        try {
            URI uri=new URI(value.trim());String host=uri.getHost(),path=uri.getRawPath();
            if(!"http".equals(uri.getScheme())||!privateIpv4(host)||uri.getRawUserInfo()!=null||uri.getRawQuery()!=null||uri.getRawFragment()!=null
                ||(path!=null&&!path.isEmpty()&&!path.equals("/"))||uri.getPort()==0||uri.getPort()>65535||uri.getPort()<-1)throw new IllegalArgumentException();
            return "http://"+host+(uri.getPort()==-1?"":":"+uri.getPort());
        }catch(Exception error) {throw new IllegalArgumentException("请填写电脑的私有 IPv4 地址，例如 http://192.168.1.8:8766");}
    }
    private static boolean privateIpv4(String host) {
        if(host==null||!host.matches("[0-9]+(?:\\.[0-9]+){3}"))return false;
        String[] parts=host.split("\\.");int[] values=new int[4];
        try {for(int i=0;i<4;i++){values[i]=Integer.parseInt(parts[i]);if(values[i]>255||!Integer.toString(values[i]).equals(parts[i]))return false;}}
        catch(NumberFormatException invalid){return false;}
        return values[0]==10||(values[0]==192&&values[1]==168)||(values[0]==172&&values[1]>=16&&values[1]<=31);
    }
    public static long delayMillis(int failures) {return failures<=0?15000L:Math.min(300000L,15000L*(1L<<Math.min(failures,5)));}
    public static boolean notificationPermission(int sdk,boolean runtimeGranted,boolean appEnabled,boolean channelEnabled) {
        return (sdk<33||runtimeGranted)&&appEnabled&&channelEnabled;
    }
}
