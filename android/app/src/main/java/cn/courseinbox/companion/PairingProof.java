package cn.courseinbox.companion;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Pure protocol verification, shared by cached and discovered endpoints. */
public final class PairingProof {
    private PairingProof() { }
    public static boolean verify(String token, String expectedId, String challenge, String address, int port, String deviceId, String proof) {
        if (token==null || token.length()<24 || expectedId==null || deviceId==null || !deviceId.matches("[0-9a-f]{32}") ||
            challenge==null || !challenge.matches("[0-9a-f]{64}") || address==null || port<1 || port>65535 ||
            proof==null || !proof.matches("[0-9a-f]{64}") || (!expectedId.isEmpty() && !expectedId.equals(deviceId))) return false;
        try {
            String message="courseinbox-pair-v1\n"+deviceId+"\n"+challenge+"\n"+address+"\n"+port;
            Mac mac=Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(token.getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
            byte[] actual=mac.doFinal(message.getBytes(StandardCharsets.UTF_8)), supplied=new byte[32];
            for(int i=0;i<32;i++) supplied[i]=(byte)Integer.parseInt(proof.substring(2*i,2*i+2),16);
            return MessageDigest.isEqual(actual,supplied);
        } catch(Exception error) { return false; }
    }
}
