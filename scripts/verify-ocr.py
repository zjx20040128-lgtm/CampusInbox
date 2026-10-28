from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parents[1]
image=Image.new('RGB',(1320,600),'#ffffff')
draw=ImageDraw.Draw(image)
font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',42)
lines=['示例数据 · 学习通课程通知','《软件工程》 第三次作业','请提交实验报告、源代码。','截止：2026年10月12日 23:59。','消息发布：2026年10月3日 16:00。']
for i,line in enumerate(lines): draw.text((64,48+i*92),line,font=font,fill='#152d2d')
image.save(root/'samples'/'sample-notice.png')
(root/'samples'/'sample-notice.txt').write_text('\n'.join(lines),encoding='utf-8')
from courseinbox.files import extract_file
text,engine=extract_file('sample-notice.png',(root/'samples'/'sample-notice.png').read_bytes(),root)
print(engine)
print(text)
(root/'docs'/'verification'/'ocr-result.txt').write_text(engine+'\n'+text,encoding='utf-8')
