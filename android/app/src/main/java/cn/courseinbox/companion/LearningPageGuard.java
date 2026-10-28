package cn.courseinbox.companion;

/** Keeps delayed page actions tied to the official page that requested them. */
public final class LearningPageGuard {
    private final int generation;
    private final String url;
    public LearningPageGuard(int generation,String url){this.generation=generation;this.url=url;}
    public boolean permits(int currentGeneration,String currentUrl,boolean active){
        return active&&generation==currentGeneration&&LearningUrls.allowed(url)&&url.equals(currentUrl);
    }
}
