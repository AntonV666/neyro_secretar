# app/calendar.py
import os
import datetime
import json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class CalendarClient:
    def __init__(self, calendar_id: str | None = None):
        """
        Обёртка над Google Calendar API.
        calendar_id = 'primary' (по умолчанию) или ID конкретного календаря.
        """
        self.calendar_id = calendar_id or os.getenv("CALENDAR_ID", "primary")

        if not os.path.exists("google_token.json"):
            raise RuntimeError("Нет файла google_token.json. Сначала авторизуйтесь через /oauth/google")

        self.creds = Credentials.from_authorized_user_file(
            "google_token.json",
            ["https://www.googleapis.com/auth/calendar"]
        )
        self.service = build("calendar", "v3", credentials=self.creds)

    # ---- CREATE ----
    def create_event(self, title, start, end, reminder_minutes=10):
        if start and end:
            body = {
                "summary": title,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
                "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": reminder_minutes}]},
            }
        elif start and isinstance(start, datetime) and start.time() == datetime.min.time():
            # если пришла только дата, создаём целодневное событие
            body = {
                "summary": title,
                "start": {"date": start.date().isoformat()},
                "end": {"date": (start.date() + timedelta(days=1)).isoformat()},
            }
        else:
            raise ValueError("Не задано корректное время начала события")

        event = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
        return {"id": event["id"], "summary": event["summary"], "when_human": start.strftime("%d.%m.%Y %H:%M") if start else "(дата)"}


    # ---- LIST ----
    def list_events(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        events_result = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        res = []
        for ev in events:
            start_str = ev["start"].get("dateTime", ev["start"].get("date"))
            res.append({
                "id": ev["id"],
                "summary": ev.get("summary", "(без названия)"),
                "human": f"{start_str}: {ev.get('summary', '')}"
            })
        return res

    # ---- MOVE ----
    def move_event(self, selector: str, new_start: datetime.datetime, new_end: datetime.datetime) -> dict:
        # ⚠️ Упрощённый вариант — ищет по подстроке в summary
        events = self.list_events(
            datetime.datetime.utcnow() - datetime.timedelta(days=30),
            datetime.datetime.utcnow() + datetime.timedelta(days=30),
        )
        for ev in events:
            if selector in ev["summary"].lower():
                body = {
                    "start": {"dateTime": new_start.isoformat()},
                    "end": {"dateTime": new_end.isoformat()},
                }
                updated = self.service.events().patch(
                    calendarId=self.calendar_id, eventId=ev["id"], body=body
                ).execute()
                return {"human": f"Перенёс {updated['summary']} на {new_start}"}
        return {"human": "Событие не найдено"}

    # ---- DELETE ----
    def delete_event(self, selector: str) -> dict:
        events = self.list_events(
            datetime.datetime.utcnow() - datetime.timedelta(days=30),
            datetime.datetime.utcnow() + datetime.timedelta(days=30),
        )
        for ev in events:
            if selector in ev["summary"].lower():
                self.service.events().delete(calendarId=self.calendar_id, eventId=ev["id"]).execute()
                return {"human": f"Удалил событие: {ev['summary']}"}
        return {"human": "Событие не найдено"}
