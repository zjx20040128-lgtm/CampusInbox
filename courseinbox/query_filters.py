"""Bounded, read-only task-query filters; unknown conditions never widen a query."""
import calendar
import re
from datetime import date, timedelta

from .core import ValidationError, normalize


def chinese_number(value):
    if value.isdigit():return int(value)
    digits={c:i for i,c in enumerate('零一二三四五六七八九')}
    if value=='十':return 10
    if '十' in value:
        left,right=value.split('十',1)
        return digits.get(left,1)*10+digits.get(right,0)
    return digits.get(value,0)


def time_window(question, moment):
    today=moment.date();consumed=[]
    dates=list(re.finditer(r'(?<!\d)(?:(\d{4})\s*(?:年|[-/])\s*)?(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})(?:日|号)?(?!\d)',question))
    if dates:
        if len(dates)>2:raise ValidationError('请指定一个日期或连续日期范围。')
        values=[]
        for match in dates:
            year=int(match[1]) if match[1] else (values[0].year if values else today.year)
            try:values.append(date(year,int(match[2]),int(match[3])))
            except ValueError:raise ValidationError('日期无效，请检查年月日。') from None
            consumed.append(match[0])
        if re.search(r'\d{1,2}(?:[:：]\d{2}|点|时)',question):
            raise ValidationError('目前按日期范围查询，请省略具体时刻。')
        if len(values)==2:
            between=question[dates[0].end():dates[1].start()]
            if not re.fullmatch(r'\s*(?:到|至|~|～|—|–|-)\s*',between):raise ValidationError('请用“到”或“至”连接日期范围。')
            if values[1]<values[0] and not dates[1][1] and int(dates[1][2])<int(dates[0][2]):
                try:values[1]=values[1].replace(year=values[0].year+1)
                except ValueError:raise ValidationError('结束日期无效。') from None
            if values[1]<values[0]:raise ValidationError('结束日期不能早于开始日期。')
            return values[0],values[1],consumed+[between]
        prefix=question[:dates[0].start()];suffix=question[dates[0].end():]
        short_end=re.match(r'\s*(?:到|至|~|～|-)\s*(\d{1,2})(?:日|号)',suffix)
        if short_end:
            try:end=values[0].replace(day=int(short_end[1]))
            except ValueError:raise ValidationError('结束日期无效。') from None
            if end<values[0]:raise ValidationError('结束日期不能早于开始日期，请补充月份。')
            return values[0],end,consumed+[short_end[0]]
        if re.match(r'\s*(?:之前|以前|前)',suffix) or re.search(r'(?:截至|截止到|不晚于)\s*$',prefix):
            return None,values[0],consumed
        if re.match(r'\s*(?:之后|以后|后|起)',suffix) or re.search(r'(?:自|从|不早于)\s*$',prefix):
            return values[0],None,consumed
        return values[0],values[0],consumed
    relative=re.search(r'今天|明天|后天|昨天|(?:本|这|上|下)(?:个)?(?:周|星期)(?:末)?|(?:未来|接下来)([一二三四五六七八九十\d]{1,3})天',question)
    if relative:
        text=relative[0];consumed.append(text)
        if text in ('今天','明天','后天','昨天'):
            start=today+timedelta(days={'今天':0,'明天':1,'后天':2,'昨天':-1}[text]);end=start
        elif relative[1]:
            count=chinese_number(relative[1])
            if not 1<=count<=366:raise ValidationError('未来天数应为1至366天。')
            start=today;end=today+timedelta(days=count-1)
        else:
            offset=7 if text.startswith('下') else -7 if text.startswith('上') else 0
            start=today-timedelta(days=today.weekday())+timedelta(days=offset);end=start+timedelta(days=6)
            if text.endswith('末'):start+=timedelta(days=5)
        if re.search(r'(?<!\d)\d{1,2}月|本月|下个月|上个月',question):raise ValidationError('请一次指定一个时间范围。')
        suffix=question[relative.end():]
        if re.match(r'\s*(?:之前|以前|前|之后|以后|后)',suffix):
            if start!=end:raise ValidationError('请使用具体日期表达之前或之后。')
            return (None,start,consumed) if re.match(r'\s*(?:之前|以前|前)',suffix) else (start,None,consumed)
        return start,end,consumed
    months=list(re.finditer(r'(?<!\d)(?:(\d{4})\s*年\s*)?([一二三四五六七八九十]{1,3}|\d{1,2})\s*月',question))
    relative=re.search(r'(本|这(?:个)?|上(?:个)?|下(?:个)?)月',question)
    if len(months)>1 or (months and relative):raise ValidationError('请一次查询一个月份，或使用具体日期范围。')
    if months:
        match=months[0];number=chinese_number(match[2])
        if re.match(r'\s*(?:之前|以前|前|之后|以后|后)',question[match.end():]):raise ValidationError('请使用具体日期表达之前或之后。')
        year=int(match[1]) if match[1] else today.year+(1 if '明年' in question else -1 if '去年' in question else 0)
        consumed=[match[0]]
    elif relative:
        shift=1 if relative[1].startswith('下') else -1 if relative[1].startswith('上') else 0
        year,offset=divmod(today.year*12+today.month-1+shift,12);number=offset+1;consumed=[relative[0]]
    else:return None
    try:start=date(year,number,1);end=date(year,number,calendar.monthrange(year,number)[1])
    except (ValueError,calendar.IllegalMonthError):raise ValidationError('年月无效，月份应为1至12月。') from None
    return start,end,consumed


def query_filters(question, tasks, moment):
    quotes=[]
    def protect(match):
        quotes.append(match[0]);return f' QUERYQUOTE{len(quotes)-1} '
    rest=re.sub(r'[“"「][^”"」]+[”"」]',protect,question)
    window=time_window(rest,moment)
    if window:
        for token in window[2]:rest=rest.replace(token,' ')
    for index,text in enumerate(quotes):rest=rest.replace(f' QUERYQUOTE{index} ',text)
    missing=re.search(r'(?:没有|无|未明确|未设置|未知|不明确)(?:的)?截止(?:时间|日期)?|截止(?:时间|日期)?(?:未明确|未知|不明确)',rest)
    if missing:rest=rest.replace(missing[0],' ')
    if missing and window:raise ValidationError('未知截止任务不能同时按截止日期筛选。')
    keyword=None
    search=re.search(r'(?:搜索|查找|查询|找一下|包含|关于)\s*[“"「]([^”"」]{1,100})[”"」]',rest)
    if not search:search=re.search(r'(?:搜索|查找|找一下)\s*([^，,。？?]{1,100}?)(?:相关(?:的)?(?:任务|作业)|(?:任务|作业)|$)',rest)
    if not search:search=re.search(r'([^，,。？?]{1,100}?)(?:什么时候|何时)(?:交|提交|截止)',rest)
    if search:keyword=search[1].strip(' 的');rest=rest.replace(search[0],' ')
    status=None
    patterns=[('active',r'未逾期|没(?:有)?逾期'),('overdue',r'(?:已(?:经)?)?(?:逾期|过期)'),
              ('active',r'尚未提交|未(?:提交|交)|没(?:有)?(?:提交|交)|待提交'),
              ('submitted',r'已(?:经)?(?:提交|交)|提交了|交了'),('pending',r'未完成|没(?:有)?完成|待开始'),
              ('done',r'已(?:经)?(?:做完|完成)'),('cancelled',r'已取消|取消的'),('all',r'所有任务|全部任务|所有作业|全部作业')]
    for value,pattern in patterns:
        match=re.search(pattern,rest)
        if match:status=value;rest=rest.replace(match[0],' ');break
    courses=[];titles=[]
    explicit=re.search(r'课程\s*[:：]\s*([^，,。？?\n]{1,100}?)(?=有(?:哪些|什么)|哪些|的任务|[，,。？?\n]|$)',rest)
    if explicit:courses=[explicit[1].strip()];rest=rest.replace(explicit[0],' ')
    if not courses:
        for name in sorted({t.get('course','') for t in tasks if t.get('course')},key=len,reverse=True):
            if name in rest:courses.append(name);rest=rest.replace(name,' ')
    if not courses:
        prefix=re.match(r'\s*([\w一-鿿]{2,40}?)\s*(?:的|有(?:哪些|什么)|还(?:有|要))',rest)
        if prefix:
            candidates={t['course'] for t in tasks if t.get('course') and normalize(prefix[1]) in normalize(t['course'])}
            if len(candidates)>1:raise ValidationError('课程简称匹配到多门课程，请填写完整课程名。')
            if candidates:courses=list(candidates);rest=rest.replace(prefix[1],' ',1)
    for name in sorted({t['title'] for t in tasks if t.get('title')},key=len,reverse=True):
        if name in rest:titles.append(name);rest=rest.replace(name,' ')
    kind=None
    for value,pattern in [('experiment',r'实验'),('exam',r'考试|测验'),('presentation',r'汇报|展示|演讲|答辩'),('project',r'论文|课程设计'),('assignment',r'作业')]:
        match=re.search(pattern,rest)
        if match:kind=value;rest=rest.replace(match[0],' ');break
    count_only=bool(re.search(r'多少|几项|几个|几条',rest))
    descending=bool(re.search(r'最晚|从晚到早|倒序',rest))
    rest=re.sub(r'^\s*我(?:的)?(?=\s*(?:还有|有哪些|哪些|有什么|有多少|有几|任务|作业|待办))','',rest)
    remainder=re.sub(r'还有|有哪些|哪些|有什么|什么|多少|几项|几个|几条|任务|作业|待办|需要|要|提交|交|的|了|请|帮我|查一下|查看|查询|搜索|找一下|查找|列出|显示|截止时间|截止日期|截止|时间|相关|包含|关于|未来|之前|以前|之后|以后|不晚于|不早于|截至|截止到|今年|明年|去年|从晚到早|最早|最晚|倒序|排序|按|到|至|前|后|自|从|起|有|还|项|条|个', '',rest)
    remainder=re.sub(r'[\W_]+','',remainder)
    return dict(window=window,missing=bool(missing),keyword=keyword,courses=courses,titles=titles,
                status=status,kind=kind,count_only=count_only,descending=descending,unrecognized=remainder,
                specific=bool(window or missing or keyword or courses or titles or status or kind))
