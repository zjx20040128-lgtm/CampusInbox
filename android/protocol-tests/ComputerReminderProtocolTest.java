import cn.courseinbox.companion.ComputerReminderProtocol;
public final class ComputerReminderProtocolTest {
    private static int assertions;
    private static void check(boolean ok,String why){assertions++;if(!ok)throw new AssertionError(why);}
    public static void main(String[] args) {
        check(ComputerReminderProtocol.endpoint(" http://192.168.1.8:8766/ ").equals("http://192.168.1.8:8766"),"normalizes explicit LAN address");
        for(String address:new String[]{"http://10.0.0.2","http://172.16.0.1:8766","http://172.31.255.254:8766"})check(ComputerReminderProtocol.endpoint(address).equals(address),"private LAN accepted");
        for(String address:new String[]{"https://192.168.1.8:8766","http://example.test:8766","http://127.0.0.1:8766","http://8.8.8.8","http://169.254.1.2","http://172.32.0.1","http://192.168.01.2","http://192.168.1.8@8.8.8.8","http://user@192.168.1.8","http://192.168.1.8/api","http://192.168.1.8?x=y","http://192.168.1.8#x","http://192.168.1.8:0","http://192.168.1.8:99999","http://[::1]"}){
            boolean rejected=false;try{ComputerReminderProtocol.endpoint(address);}catch(IllegalArgumentException expected){rejected=true;}check(rejected,"reject unsafe address: "+address);
        }
        check(ComputerReminderProtocol.delayMillis(0)==15000&&ComputerReminderProtocol.delayMillis(1)==30000&&ComputerReminderProtocol.delayMillis(20)==300000,"offline backoff bounded; connected poll 15s");
        check(ComputerReminderProtocol.notificationPermission(26,false,true,true),"Android 8 needs no runtime permission");
        check(!ComputerReminderProtocol.notificationPermission(33,false,true,true),"Android13 notification permission independent of listener access");
        check(!ComputerReminderProtocol.notificationPermission(35,true,false,true)&&!ComputerReminderProtocol.notificationPermission(35,true,true,false),"app/channel disable gates delivery");
        System.out.println("Computer reminder protocol: "+assertions+" assertions passed");
    }
}
