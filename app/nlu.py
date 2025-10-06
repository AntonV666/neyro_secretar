# app/nlu.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import dateparser
from dateparser.search import search_dates


@dataclass
class Intent:
    type: str  # create | list | move | delete | unknown
    # create
    title: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    # list
    range_start: Optional[datetime] = None
    range_end: Optional[datetime] = None
    # move/delete (упрощённо)
    selector: Optional[str] = None
    new_start: Optional[datetime] = None
    new_end: Optional[datetime] = None


# ---------- нормализация времени ----------

# HH.MM -> HH:MM ; "15 15" -> "15:15" ; "1515" -> "15:15" (но НЕ трогаем yyyy вроде 2025)
_RE_HH_DOT_MM   = re.compile(r"\b(\d{1,2})\.(\d{2})\b")
_RE_HH_SPACE_MM = re.compile(r"\b(\d{1,2})\s+(\d{2})\b")
_RE_HHMM        = re.compile(r"(?<![\d.:/\-])(\d{3,4})(?![\d.:/\-])")  # не рядом с разделителями дат

WEEKDAYS = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
    "понед", "втор", "сред", "четв", "пятн", "субб", "воскр",
]

# слова про время/дату + служебные глаголы-команды
STOP_WORDS = set([
    "сегодня", "завтра", "послезавтра", "после", "через",
    "минут", "минуты", "минуту", "час", "часа", "часов",
    "день", "дня", "дней", "неделю", "недели", "недель",
    "месяц", "месяца", "месяцев",
    "в", "к", "на", "во",
    # команды
    "напомни", "напоминание", "напоминалку", "напомнить",
    "создай", "создать", "сделай", "сделать", "поставь", "поставить",
]) | set(WEEKDAYS)

# чтобы вырезать из текста саму «временную часть» при построении title
_TIME_PATTERNS = [
    r"\bв\s*\d{1,2}:\d{2}\b",
    r"\bв\s*\d{1,2}\.\d{2}\b",
    r"\bв\s*\d{3,4}\b",
    r"\bв\s*\d{1,2}\s+\d{2}\b",
]
_RE_TIME_BLOCKS = [re.compile(pat, flags=re.IGNORECASE) for pat in _TIME_PATTERNS]


def _normalize_time_tokens(text: str) -> str:
    s = text

    # HH.MM → HH:MM
    s = _RE_HH_DOT_MM.sub(lambda m: f"{int(m.group(1)):02d}:{m.group(2)}", s)

    # "15 15" → "15:15"
    def _space_to_colon(m: re.Match) -> str:
        hh, mm = int(m.group(1)), m.group(2)
        if 0 <= hh <= 23:
            return f"{hh:02d}:{mm}"
        return m.group(0)
    s = _RE_HH_SPACE_MM.sub(_space_to_colon, s)

    # 1515/0915 → 15:15/09:15 (но НЕ трогаем 2025 и т.п.)
    def _hhmm(m: re.Match) -> str:
        val = m.group(1)
        if len(val) in (3, 4):
            hh = int(val[:-2])
            mm = val[-2:]
            if 0 <= hh <= 23:
                return f"{hh:02d}:{mm}"
        return m.group(0)
    s = _RE_HHMM.sub(_hhmm, s)

    return s


def _clean_title(text: str) -> str:
    s = text.lower()

    # вырезаем явные временные блоки «в 15:15», «в 15 15», «в 1515», «в 15.15»
    for rx in _RE_TIME_BLOCKS:
        s = rx.sub(" ", s)

    # токенизируем и убираем стоп-слова
    tokens = [t for t in re.split(r"\s+", s) if t]
    tokens = [t for t in tokens if t not in STOP_WORDS]

    # собираем обратно
    s = " ".join(tokens)
    s = re.sub(r"[^\wа-яё0-9\s\-]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s).strip()

    # если всё вырезали — вернём исходник, но без краевых пробелов
    return s or text.strip()


def _choose_best_match(matches, now: datetime) -> Optional[datetime]:
    """
    Нормализуем результаты search_dates к списку (text, datetime) и выбираем
    наиболее подходящую будущую дату. Иногда search_dates отдаёт:
    - список кортежей: [(substring, dt), ...]
    - список словарей: [{"text": "...", "date_obj": dt}, ...]
    - список самих datetime: [dt1, dt2, ...]
    """
    norm: List[Tuple[str, datetime]] = []
    for item in matches:
        if isinstance(item, tuple) and len(item) >= 2:
            txt, dt = item[0], item[1]
        elif isinstance(item, dict):
            txt = item.get("text", "")
            dt = item.get("date_obj") or item.get("date") or item.get("datetime")
            if dt is None and isinstance(item.get("data"), datetime):
                dt = item["data"]
        elif isinstance(item, datetime):
            txt, dt = "", item
        else:
            continue
        if isinstance(dt, datetime):
            norm.append((str(txt), dt))

    if not norm:
        return None

    time_like = re.compile(r"\b\d{1,2}[:.]\d{2}\b|\b\d{3,4}\b")
    with_time = [dt for txt, dt in norm if time_like.search(txt)]
    candidate = with_time[0] if with_time else norm[-1][1]

    # отбрасываем «прошлое/прямо сейчас» (≤ 60 сек), чтобы не было мгновенных срабатываний
    if candidate <= now + timedelta(seconds=60):
        return None
    return candidate



def _parse_when(text: str, tz: str) -> Optional[datetime]:
    """
    Ищем дату/время в строке устойчиво:
    - нормализуем «15.15 / 15 15 / 1515»
    - search_dates достаёт дату из «шума»
    - предпочитаем ближайшее будущее
    """
    normalized = _normalize_time_tokens(text)
    now = datetime.now()

    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": now,
        "RETURN_AS_TIMEZONE_AWARE": False,   # вернём naive, дальше обработаем в календаре
        "LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD": 0.0,
    }

    # сначала быстрый parse (на случай «сегодня в 16:02» без лишних слов)
    dt = dateparser.parse(normalized, languages=["ru"], settings=settings)
    if dt and dt > now + timedelta(seconds=60):
        return dt

    # если парсер споткнулся — ищем внутри строки
    found = search_dates(normalized, languages=["ru"], settings=settings)
    if not found:
        return None

    return _choose_best_match(found, now)


# ---------- основной парсер ----------

def parse_intent(text: str, tz: str = "Asia/Yekaterinburg") -> Intent:
    """
    Простой NLU:
    - пытается создать событие (вытаскивает when + title)
    - 'list' / 'move' / 'delete' — упрощённые заглушки
    """
    t = text.strip()

    # 1) create
    when = _parse_when(t, tz)
    if when:
        title = _clean_title(t)
        end = when + timedelta(minutes=30)
        return Intent(type="create", title=title, start=when, end=end)

    # 2) list (очень грубо)
    low = t.lower()
    if any(kw in low for kw in ["что у меня", "расписан", "покажи план"]):
        start = datetime.now()
        end = start + timedelta(days=1)
        return Intent(type="list", range_start=start, range_end=end)
    if "сегодня" in low:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return Intent(type="list", range_start=start, range_end=end)
    if "завтра" in low:
        start = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return Intent(type="list", range_start=start, range_end=end)

    # 3) move / delete — заглушки (чтобы не ломать main.py)
    if any(kw in low for kw in ["перенеси", "перенос"]):
        return Intent(type="move", selector=t)
    if any(kw in low for kw in ["удали", "отмени"]):
        return Intent(type="delete", selector=t)

    return Intent(type="unknown")
