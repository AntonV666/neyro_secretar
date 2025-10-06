# app/main.py
import asyncio
import logging
import os
from pathlib import Path
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile

from app.nlu import parse_intent
from app.calendar_client import CalendarClient
from app.storage import Storage
from app.stt import transcribe_voice
from app.tts import synthesize_tts_async


# ---------- CONFIG ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)

TZ = os.getenv("TZ", "Asia/Yekaterinburg")
SCHED_TZ = ZoneInfo(TZ)  # единая TZ для всего
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
OWNER_ID = int(os.getenv("TG_OWNER_ID", "0"))
REMINDER_MIN = int(os.getenv("REMINDER_MINUTES_BEFORE", "30"))        # напоминание Google
BOT_REMINDER_MIN = int(os.getenv("BOT_REMINDER_MINUTES_BEFORE", "15"))  # напоминание бота

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(
    timezone=SCHED_TZ,
    job_defaults={
        "coalesce": True,
        "misfire_grace_time": 60,
    },
)

cal = CalendarClient()
db = Storage("sqlite.db")

HELP_TEXT = (
    "Не поняла запрос. Вот примеры того, как можно задавать напоминания:\n\n"
    "• завтра в 10:00 напомни оплатить хостинг\n"
    "• через 2 часа позвонить маме\n"
    "• в пятницу в 14 встреча с Иваном на час\n"
    "• создай встречу завтра в 15:30 с клиентом\n"
    "• через 45 минут проверить сервер\n"
    "• во вторник в 9 утра совещание на полтора часа\n"
    "• через неделю в 18:00 тренировка\n"
    "• в понедельник в 11:00 запись к врачу\n"
    "• напомни через 10 минут выключить чайник\n"
    "• в субботу в 19:00 поход в кино\n"
    "• завтра в обед встреча с командой на 30 минут\n"
    "• через 3 дня в 8 утра звонок директору\n"
    "• 25 декабря в 20:00 поздравить родителей\n"
    "• сегодня в 22:00 напомни проверить логи\n"
    "• на следующей неделе во вторник в 14:00 встреча в офисе\n"
)


# ---------- HELPERS ----------
def _ensure_aware(dt: datetime) -> datetime:
    """Привести datetime к timezone-aware в TZ из .env."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=SCHED_TZ)
    return dt.astimezone(SCHED_TZ)


async def _send_bot_reminder(summary: str, start_dt: datetime):
    try:
        await bot.send_message(
            OWNER_ID,
            f"🔔 Напоминание: «{summary}» (в {start_dt.strftime('%H:%M')})", # f"🔔 Напоминание: «{summary}» через {BOT_REMINDER_MIN} мин. (в {start_dt.strftime('%H:%M')})",
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке напоминания: {e}")


def _safe_schedule_bot_reminder(summary: str, start_dt: datetime) -> None:
    """Ставит локальное напоминание от бота за BOT_REMINDER_MIN минут."""
    start = _ensure_aware(start_dt)
    remind_at = start - timedelta(minutes=BOT_REMINDER_MIN)
    now = datetime.now(SCHED_TZ)

    if remind_at <= now:
        # если момент напоминания уже прошёл — шлём сразу
        asyncio.create_task(_send_bot_reminder(summary, start))
    else:
        # регистрируем асинхронную задачу напрямую
        scheduler.add_job(
            _send_bot_reminder,
            trigger=DateTrigger(run_date=remind_at),
            args=[summary, start],   # 👈 передаём параметры
        )


async def send_reply(m: Message, text: str, reply_mode: str = "text"):
    """Ответить текстом или голосом (с TTS fallback в текст)."""
    if reply_mode == "voice":
        try:
            voice_path = await synthesize_tts_async(text, out_dir="./tmp_tts")
            await m.answer_voice(voice=FSInputFile(str(voice_path)))
        except Exception as e:
            logging.error(f"TTS error: {e}")
            await m.answer(text)  # fallback в текст
    else:
        await m.answer(text)


# ---------- HANDLERS ----------
@dp.message(F.from_user.id != OWNER_ID)
async def deny_for_others(m: Message):
    await m.answer("Извини, этот бот — личный помощник владельца.")


@dp.message(F.voice)
async def handle_voice(m: Message):
    # сохраняем voice в ./tmp
    tmp_path = Path(f"./tmp/{m.voice.file_unique_id}.ogg")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    file = await bot.get_file(m.voice.file_id)
    try:
        await bot.download(file, destination=tmp_path)
    except Exception:
        await bot.download_file(file.file_path, destination=tmp_path)

    # STT → текст
    try:
        text = transcribe_voice(str(tmp_path))
    except Exception as e:
        await m.answer(f"Не смог распознать голос: {e}")
        return

    logging.info(f"[STT] распознано: {text!r}")

    # обработка текста, ответ голосом
    await process_text(m, text, reply_mode="voice")


@dp.message(F.text)
async def handle_text(m: Message):
    await process_text(m, m.text, reply_mode="text")


# ---------- CORE ----------
async def process_text(m: Message, text: str, reply_mode: str = "text"):
    intent = parse_intent(text, tz=TZ)

    if intent.type == "create":
        if not intent.start:
            await send_reply(m, HELP_TEXT, reply_mode)
            return

        event = cal.create_event(
            intent.title,
            intent.start,
            intent.end,
            reminder_minutes=REMINDER_MIN,  # уведомление Google (popup)
        )

        text_ok = (
            f"Создала событие «{event['summary']}» на {event['when_human']}. "
            f"Напомню за {BOT_REMINDER_MIN} мин."
        )
        await send_reply(m, text_ok, reply_mode)

        # телеграм-напоминание от бота
        _safe_schedule_bot_reminder(event['summary'], intent.start)

    elif intent.type == "list":
        events = cal.list_events(intent.range_start, intent.range_end)
        if not events:
            await send_reply(m, "Ничего не запланировано.", reply_mode)
        else:
            pretty = "\n".join([e["human"] for e in events])
            await send_reply(m, pretty, reply_mode)

    elif intent.type == "move":
        res = cal.move_event(intent.selector, intent.new_start, intent.new_end)
        await send_reply(m, res["human"], reply_mode)

    elif intent.type == "delete":
        res = cal.delete_event(intent.selector)
        await send_reply(m, res["human"], reply_mode)

    else:
        await send_reply(m, HELP_TEXT, reply_mode)


# ---------- ENTRY ----------
async def main():
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

