import cn.courseinbox.companion.ListenerRecoverySchedule;

public final class ListenerRecoveryScheduleTest {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args){
        check(ListenerRecoverySchedule.delayMillis(0)==15000,"first post-upgrade retry waits for package manager to settle");
        check(ListenerRecoverySchedule.delayMillis(1)==60000,"second retry is bounded");
        check(ListenerRecoverySchedule.delayMillis(2)==180000,"third retry backs off");
        check(ListenerRecoverySchedule.delayMillis(3)==600000,"last retry tolerates OEM delay");
        check(ListenerRecoverySchedule.delayMillis(4)<0,"recovery stops after a bounded number of attempts");
        System.out.println("PASS: bounded listener recovery schedule");
    }
}
