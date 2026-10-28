package cn.courseinbox.companion;

/** Bounded delays for notification-listener recovery after an app upgrade. */
public final class ListenerRecoverySchedule {
    private static final long[] DELAYS={15000L,60000L,180000L,600000L};
    private ListenerRecoverySchedule(){}
    public static long delayMillis(int attempt){return attempt>=0&&attempt<DELAYS.length?DELAYS[attempt]:-1;}
}
