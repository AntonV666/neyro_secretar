# app/calendar_client.py

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional   # 👈 добавили

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _ensure_rfc3339(dt: datetime) -> str:
    """
    Приводит datetime к RFC3339.
    Если datetime «naive», добавляем локальный TZ из TZ или UTC.
    """
    if dt.tzinfo is None:
        # пробуем взять TZ из окружения, иначе UTC
        tz_name = os.getenv("TZ")
        if tz_name:
            # минимальная безопасная привязка: смещение по текущему времени
            # (для большинства рабочих сценариев достаточно)
            offset = datetime.now().astimezone().utcoffset() or timedelta(0)
            tz = timezone(offset)
        else:
            tz = timezone.utc
        dt = dt.replace(tzinfo=tz)
    return dt.isoformat()


class CalendarClient:
    def __init__(self, calendar_id: str | None = None):
        """
        Обёртка над Google Calendar API.
        calendar_id = 'primary' (по умолчанию) или ID конкретного календаря.
        """
        self.calendar_id = calendar_id or os.getenv("CALENDAR_ID", "primary")

        # Абсолютный путь к корню проекта
        ROOT_DIR = Path(__file__).resolve().parents[1]

        # ✅ Ищем ТУТ по умолчанию: .../state/google_token.json
        default_token = ROOT_DIR / "state" / "google_token.json"

        # Можно переопределить через переменную окружения GOOGLE_TOKEN_PATH
        token_path = Path(os.getenv("GOOGLE_TOKEN_PATH", default_token)).resolve()

        if not token_path.exists():
            raise RuntimeError(
                f"Нет файла google_token.json. Ожидался по пути: {token_path}\n"
                "Сначала авторизуйтесь через /oauth/google или укажите GOOGLE_TOKEN_PATH."
            )

        self.creds = Credentials.from_authorized_user_file(
            str(token_path),
            ["https://www.googleapis.com/auth/calendar"]
        )
        self.service = build("calendar", "v3", credentials=self.creds)

    # ---- CREATE ----
    # app/calendar_client.py — замените метод create_event целиком
    def create_event(self, title, start, end, reminder_minutes=30):
        tz_name = os.getenv("TZ", "UTC")

        def _dt_payload(dt: datetime) -> Dict[str, str]:
            # Google принимает либо ISO со смещением (если aware),
            # либо naive + отдельное поле "timeZone".
            if dt.tzinfo:
                return {"dateTime": dt.isoformat()}  # уже aware, смещение внутри строки
            else:
                return {"dateTime": dt.isoformat(), "timeZone": tz_name}

        if start and end:
            body = {
                "summary": title,
                "start": _dt_payload(start),
                "end": _dt_payload(end),
                "reminders": {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": reminder_minutes}],
                },
            }
        elif start and isinstance(start, datetime) and start.time() == datetime.min.time():
            # целодневное событие — здесь НЕЛЬЗЯ dateTime, только date
            body = {
                "summary": title,
                "start": {"date": start.date().isoformat()},
                "end": {"date": (start.date() + timedelta(days=1)).isoformat()},
                "reminders": {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": reminder_minutes}],
                },
            }
        else:
            raise ValueError("Не задано корректное время начала события")

        event = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
        return {
            "id": event["id"],
            "summary": event.get("summary", title),
            "when_human": start.strftime("%d.%m.%Y %H:%M") if start else "(дата)",
        }


    # ---- LIST ----
    def list_events(self, start: datetime, end: datetime) -> List[Dict]:
        """
        Возвращает список событий в диапазоне [start, end) с красивым полем 'human'.
        Поддержка пагинации.
        """
        items: List[Dict] = []
        page_token = None
        while True:
            response = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=_ensure_rfc3339(start),
                timeMax=_ensure_rfc3339(end),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token
            ).execute()

            for ev in response.get("items", []):
                # start может быть dateTime (обычное событие) или date (целодневное)
                start_dt = ev.get("start", {})
                end_dt = ev.get("end", {})
                summary = ev.get("summary", "(без названия)")

                if "dateTime" in start_dt:
                    when = start_dt["dateTime"]
                    # человекочитаемо
                    try:
                        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
                        human = f"{dt.strftime('%d.%m.%Y %H:%M')}: {summary}"
                    except Exception:
                        human = f"{when}: {summary}"
                else:
                    # целодневное
                    date_str = start_dt.get("date")
                    human = f"{date_str}: {summary}" if date_str else summary

                items.append({
                    "id": ev["id"],
                    "summary": summary,
                    "start": start_dt,
                    "end": end_dt,
                    "human": human,
                })

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return items

    # ---- MOVE ----
    def move_event(self, selector: str, new_start: datetime, new_end: Optional[datetime]) -> Dict[str, str]:
        """
        Перенос события по подстроке selector (без регистра).
        Берём ближайшее будущее событие, иначе самое свежее прошлое.
        """
        now = datetime.now(timezone.utc)
        events = self.list_events(
            now - timedelta(days=30),
            now + timedelta(days=365),
        )

        sel = selector.lower()
        matches = [e for e in events if sel in e["summary"].lower()]

        if not matches:
            return {"human": "Событие не найдено"}

        # сортируем: сначала будущие по времени начала, потом прошлые (по убыванию)
        def _start_dt(ev: Dict) -> datetime:
            s = ev["start"]
            if "dateTime" in s:
                return datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00"))
            # для целодневных берём начало дня в UTC
            return datetime.fromisoformat(s["date"] + "T00:00:00+00:00")

        future = [e for e in matches if _start_dt(e) >= now]
        if future:
            target = sorted(future, key=_start_dt)[0]
        else:
            target = sorted(matches, key=_start_dt, reverse=True)[0]

        if new_end is None:
            new_end = new_start + timedelta(minutes=30)

        body = {
            "start": {"dateTime": _ensure_rfc3339(new_start)},
            "end": {"dateTime": _ensure_rfc3339(new_end)},
        }
        updated = self.service.events().patch(
            calendarId=self.calendar_id, eventId=target["id"], body=body
        ).execute()
        return {"human": f"Перенёс «{updated.get('summary', '')}» на {new_start.strftime('%d.%m.%Y %H:%M')}"}

    # ---- DELETE ----
    def delete_event(self, selector: str) -> Dict[str, str]:
        """
        Удаляет событие по подстроке selector (без регистра).
        Логика выбора — как в move_event.
        """
        now = datetime.now(timezone.utc)
        events = self.list_events(
            now - timedelta(days=30),
            now + timedelta(days=365),
        )

        sel = selector.lower()
        matches = [e for e in events if sel in e["summary"].lower()]

        if not matches:
            return {"human": "Событие не найдено"}

        def _start_dt(ev: Dict) -> datetime:
            s = ev["start"]
            if "dateTime" in s:
                return datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00"))
            return datetime.fromisoformat(s["date"] + "T00:00:00+00:00")

        future = [e for e in matches if _start_dt(e) >= now]
        if future:
            target = sorted(future, key=_start_dt)[0]
        else:
            target = sorted(matches, key=_start_dt, reverse=True)[0]

        self.service.events().delete(calendarId=self.calendar_id, eventId=target["id"]).execute()
        return {"human": f"Удалил событие: {target['summary']}"}

