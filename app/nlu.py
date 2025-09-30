# app/nlu.py
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
import dateparser
from dateparser.search import search_dates

@dataclass
class Intent:
    type: str
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    range_start: datetime | None = None
    range_end: datetime | None = None
    selector: str | None = None
    new_start: datetime | None = None
    new_end: datetime | None = None
    timedelta: callable = timedelta

RULES_CREATE = ["напомни", "создай", "встреча", "запиши"]

def _extract_dt_and_title(text: str, tz: str) -> tuple[datetime | None, str]:
    """
    Ищем дату/время в тексте, остальное считаем заголовком.
    """
    settings = {"TIMEZONE": tz, "RETURN_AS_TIMEZONE_AWARE": True}
    found = search_dates(text, languages=["ru"], settings=settings)
    if not found:
        # отдельная попытка: весь текст как дата (вдруг он короткий)
        when = dateparser.parse(text, languages=["ru"], settings=settings)
        return when, text

    # Берём ПЕРВОЕ найденное совпадение
    span_text, when = found[0]

    # Убираем найденный фрагмент и служебные глаголы — остаётся заголовок
    title = text
    title = title.replace(span_text, " ")
    for k in RULES_CREATE:
        title = re.sub(rf"\b{k}\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        title = "Напоминание"

    return when, title

def parse_intent(text: str, tz: str = "Asia/Almaty") -> Intent:
    t = text.lower().strip()

    # ---- CREATE ----
    if any(k in t for k in RULES_CREATE):
        when, title = _extract_dt_and_title(text, tz)
        end = (when + timedelta(minutes=30)) if when else None
        return Intent(type="create", title=title, start=when, end=end)

    # ---- LIST ----
    if "что у меня" in t or "покажи" in t:
        now = dateparser.parse(
            "сейчас", languages=["ru"],
            settings={"TIMEZONE": tz, "RETURN_AS_TIMEZONE_AWARE": True}
        )
        if "сегодня" in t:
            rs = now.replace(hour=0, minute=0, second=0, microsecond=0)
            re_ = rs + timedelta(days=1)
        elif "завтра" in t:
            rs = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            re_ = rs + timedelta(days=1)
        else:  # неделя
            rs = now
            re_ = now + timedelta(days=7)
        return Intent(type="list", range_start=rs, range_end=re_)

    # ---- MOVE ----
    if "перенеси" in t:
        when, _ = _extract_dt_and_title(text, tz)
        end = (when + timedelta(minutes=30)) if when else None
        return Intent(type="move", selector=text.lower(), new_start=when, new_end=end)

    # ---- DELETE ----
    if "удали" in t:
        return Intent(type="delete", selector=text.lower())

    return Intent(type="unknown")

