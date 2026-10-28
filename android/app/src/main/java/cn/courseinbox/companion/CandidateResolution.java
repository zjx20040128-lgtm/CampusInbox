package cn.courseinbox.companion;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

/** Limit each asynchronous candidate independently of the overall discovery budget. */
public final class CandidateResolution {
    public interface Operation<T>{void start(Consumer<T> callback);void cancel();}
    private CandidateResolution(){}
    public static <T> T await(Operation<T> operation,long deadline,int limitMillis)throws Exception {
        long remaining=deadline-System.nanoTime();
        if(remaining<=0)return null;
        CountDownLatch complete=new CountDownLatch(1);AtomicReference<T> result=new AtomicReference<>();
        try {
            operation.start(value->{result.set(value);complete.countDown();});
            long wait=Math.min(TimeUnit.MILLISECONDS.toNanos(limitMillis),deadline-System.nanoTime());
            return wait>0&&complete.await(wait,TimeUnit.NANOSECONDS)?result.get():null;
        } finally {operation.cancel();}
    }
}
