# Neyro Secretar — личный нейро-секретарь

Телеграм-бот, который понимает естественные фразы на русском и работает с Google Calendar:
- создаёт события «человеческими» командами: _«завтра в 10:00 напомни оплатить хостинг»_;
- показывает что запланировано _(«что у меня сегодня?»)_;
- переносит/удаляет встречи;
- шлёт дублирующее напоминание в Telegram (например, за 15 минут до события), помимо стандартного оповещения Google.

## Технологии
- **Python 3.12**, **aiogram 3**, **FastAPI** (OAuth callback)
- **Google Calendar API**
- **dateparser**, **APScheduler**
- STT: **Vosk** (по умолчанию) / опционально Whisper/API
- TTS: **edge-tts** с фолбэком на **gTTS**
- Dockerfile и docker-compose для развёртывания

## Быстрый старт (локально)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # заполни переменные
# положи client_secret.json (из Google Cloud Console)
# авторизация: запусти OAuth-сервер и пройди по ссылке
uvicorn app.oauth_server:app --host 127.0.0.1 --port 8080
# после успешного OAuth появится google_token.json

# запуск бота
python -m app.main