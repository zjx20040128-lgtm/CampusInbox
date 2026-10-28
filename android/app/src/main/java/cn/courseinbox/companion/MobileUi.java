package cn.courseinbox.companion;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.widget.*;

final class MobileUi {
    static final int GREEN=Color.rgb(36,91,72),INK=Color.rgb(33,56,49),MUTED=Color.rgb(112,129,120),BG=Color.rgb(246,247,244),RED=Color.rgb(170,51,51),SOFT_GREEN=Color.rgb(232,241,234),LINE=Color.rgb(231,236,231),WHITE=Color.WHITE;
    private final Context context;
    MobileUi(Context context){this.context=context;}
    int dp(int value){return Math.round(value*context.getResources().getDisplayMetrics().density);}
    LinearLayout column(){LinearLayout view=new LinearLayout(context);view.setOrientation(LinearLayout.VERTICAL);return view;}
    GradientDrawable background(int color,int radius){GradientDrawable view=new GradientDrawable();view.setColor(color);view.setCornerRadius(dp(radius));return view;}
    TextView text(String value,int size,int color,boolean bold){TextView view=new TextView(context);view.setText(value);view.setTextSize(size);view.setTextColor(color);view.setPadding(0,dp(6),0,dp(6));if(bold)view.setTypeface(Typeface.DEFAULT,Typeface.BOLD);return view;}
    LinearLayout card(LinearLayout parent){LinearLayout view=column();view.setPadding(dp(18),dp(14),dp(18),dp(14));GradientDrawable shape=background(WHITE,16);shape.setStroke(dp(1),LINE);view.setBackground(shape);LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.topMargin=dp(10);parent.addView(view,params);return view;}
    TextView smallAction(String label,Runnable action){TextView view=text(label,13,GREEN,true);view.setGravity(android.view.Gravity.CENTER);view.setPadding(dp(12),dp(7),dp(12),dp(7));view.setMinHeight(dp(40));view.setBackground(background(SOFT_GREEN,12));view.setOnClickListener(v->action.run());return view;}
    TextView tab(String label,boolean selected,Runnable action){TextView view=text(label,14,selected?GREEN:MUTED,selected);view.setGravity(android.view.Gravity.CENTER);view.setPadding(dp(8),dp(5),dp(8),dp(5));view.setMinHeight(dp(44));view.setBackground(background(selected?SOFT_GREEN:WHITE,14));view.setOnClickListener(v->action.run());return view;}
    Button button(LinearLayout parent,String label,boolean primary,Runnable action){Button button=new Button(context);button.setText(label);button.setAllCaps(false);button.setTextSize(14);button.setTextColor(primary?Color.WHITE:GREEN);button.setMinWidth(0);button.setMinimumWidth(0);button.setMinHeight(dp(48));button.setSingleLine(false);button.setPadding(dp(12),dp(10),dp(12),dp(10));button.setBackgroundTintList(null);button.setBackground(background(primary?GREEN:Color.rgb(234,241,233),10));button.setOnClickListener(v->action.run());LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.topMargin=dp(7);parent.addView(button,params);return button;}
    EditText input(LinearLayout parent,String label,String value){parent.addView(text(label,13,MUTED,false));EditText input=new EditText(context);input.setText(value);input.setTextSize(15);input.setTextColor(INK);input.setPadding(dp(8),dp(10),dp(8),dp(10));parent.addView(input,new LinearLayout.LayoutParams(-1,-2));return input;}
}
