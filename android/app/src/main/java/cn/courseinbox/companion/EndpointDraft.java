package cn.courseinbox.companion;

/** A background address update must never replace an unsaved user edit. */
public final class EndpointDraft {
    private String baseline,draft;
    public EndpointDraft(String initial){baseline=initial;draft=initial;}
    public void edited(String value){draft=value;}
    public void saved(String value){baseline=value;draft=value;}
    public String automatic(String value){if(draft.equals(baseline)){baseline=value;draft=value;}return draft;}
}
