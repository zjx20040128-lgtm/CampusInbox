"""Resolve an answer window using source years, never the machine/scan date."""
import re
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))
_POINT = r'(?:(20\d{2})[-年/.])?(\d{1,2})[-月/.](\d{1,2})日?\s+(\d{1,2})[:：](\d{2})(?::(\d{2}))?'
_WINDOW = re.compile(r'作答时间\s*[:：]?\s*' + _POINT + r'\s*至\s*' + _POINT + r'(?![\d:：])')


def deadline_from_window(text, published_at=None):
    windows = list(_WINDOW.finditer(text or ''))
    if len(windows) != 1:
        return None
    parts = windows[0].groups()
    start, end = parts[:6], parts[6:]
    try:
        anchor = datetime.fromisoformat(published_at.replace('Z', '+00:00')) if published_at else None
        if anchor and anchor.tzinfo:
            anchor = anchor.astimezone(CN)
        elif anchor:
            # Only an explicit date-only publication is a valid timezone-free basis.
            anchor = anchor.replace(tzinfo=CN) if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', published_at) else None
        if start[0]:
            years = [int(start[0])]
        elif end[0]:
            years = [int(end[0])-1, int(end[0])]
        elif anchor:
            years = [anchor.year-1, anchor.year, anchor.year+1]
        else:
            return None
        found = set()
        for year in years:
            try:
                first = datetime(year, *map(int, start[1:5]), int(start[5] or 0), tzinfo=CN)
                last_year = int(end[0]) if end[0] else year + (tuple(map(int,end[1:5])) < tuple(map(int,start[1:5])))
                last = datetime(last_year, *map(int, end[1:5]), int(end[5] or 0), tzinfo=CN)
            except ValueError:
                continue
            # No long-range guess: yearless windows need nearby publication evidence.
            if not start[0] and not end[0] and abs(first-anchor) > timedelta(days=31):
                continue
            if timedelta(0) < last-first <= timedelta(days=183):
                found.add(last.isoformat())
        return next(iter(found)) if len(found) == 1 else None
    except (ValueError, TypeError, AttributeError):
        return None
