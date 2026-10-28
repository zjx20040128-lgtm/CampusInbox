import cn.courseinbox.companion.PairingProof;
public class PairingProofTest {
 static final String TOKEN="test-token-which-is-long-and-not-a-real-secret", ID="0123456789abcdef0123456789abcdef", NONCE=new String(new char[64]).replace('\0','a'), PROOF="5f411416cb9ad795ba1992d132238b551d92787f056b7184e1d84c7c80c3f25e";
 static void check(boolean value) { if(!value) throw new AssertionError(); }
 public static void main(String[] args) {
  check(PairingProof.verify(TOKEN,ID,NONCE,"10.1.2.3",8765,ID,PROOF));
  check(PairingProof.verify(TOKEN,"",NONCE,"10.1.2.3",8765,ID,PROOF));
  check(!PairingProof.verify(TOKEN+"x",ID,NONCE,"10.1.2.3",8765,ID,PROOF));
  check(!PairingProof.verify(TOKEN,"11111111111111111111111111111111",NONCE,"10.1.2.3",8765,ID,PROOF));
  check(!PairingProof.verify(TOKEN,ID,NONCE.substring(1)+"b","10.1.2.3",8765,ID,PROOF));
  check(!PairingProof.verify(TOKEN,ID,NONCE,"10.1.2.4",8765,ID,PROOF));
  check(!PairingProof.verify(TOKEN,ID,NONCE,"10.1.2.3",8766,ID,PROOF));
  check(!PairingProof.verify(TOKEN,ID,NONCE,"10.1.2.3",8765,ID,"00"));
  System.out.println("Pairing proof: 8 assertions passed");
 }
}
