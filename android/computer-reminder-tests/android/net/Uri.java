package android.net;
import java.net.URLEncoder;import java.nio.charset.StandardCharsets;
public final class Uri {private final String value;private Uri(String value){this.value=value;}public static Uri parse(String value){return new Uri(value);}public static String encode(String value){return URLEncoder.encode(value,StandardCharsets.UTF_8);}public String toString(){return value;}}
