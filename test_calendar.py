from __future__ import print_function
import datetime
import os.path
import json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Файл с токенами, который сохранил твой oauth_server.py
TOKEN_PATH = "google_token.json"

def main():
    if not os.path.exists(TOKEN_PATH):
        print("❌ Нет google_token.json. Сначала пройди авторизацию через /oauth/google")
        return

    # Загружаем сохранённые креды
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, ["https://www.googleapis.com/auth/calendar"])

    # Создаём сервис для работы с API Calendar
    service = build("calendar", "v3", credentials=creds)

    # Берём текущее время (UTC) и читаем ближайшие 5 событий
    now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' = UTC
    print(f"📅 События из календаря начиная с {now}:")

    events_result = service.events().list(
        calendarId="primary", timeMin=now,
        maxResults=5, singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = events_result.get("items", [])

    if not events:
        print("Нет предстоящих событий.")
    else:
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            print(f"- {start}: {event['summary']}")

if __name__ == "__main__":
    main()
