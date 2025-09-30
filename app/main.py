import asyncio
import logging
import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile

from nlu import parse_intent
from calendar_client import CalendarClient
from storage import Storage
from stt import transcribe_voice
from tts import synthesize_tts_async


# ---------- CONFIG ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)

TZ = os.getenv("TZ", "Asia/Yekaterinburg")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
OWNER_ID = int(os.getenv("TG_OWNER_ID", "0"))
REMINDER_MIN = int(os.getenv("REMINDER_MINUTES_BEFORE", "25"))

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)
cal = CalendarClient()
db = Storage("sqlite.db")


# ---------- HELPERS ----------
async def send_reply(m: Message, text: str, reply_mode: str = "text"):
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
            await send_reply(
                m,
                "Не понял дату/время. Примеры:\n"
                "• завтра в 10:00 напомни оплатить хостинг\n"
                "• через 2 часа позвонить маме\n"
                "• в пятницу в 14 встреча с Иваном на час",
                reply_mode,
            )
            return

        event = cal.create_event(
            intent.title,
            intent.start,
            intent.end,
            reminder_minutes=REMINDER_MIN,
        )

        text_ok = (
            f"Создал событие *{event['summary']}* на {event['when_human']}. "
            f"Напомню за {REMINDER_MIN} мин."
        )

        if reply_mode == "text":
            await m.answer(text_ok, parse_mode="Markdown")
        else:
            await send_reply(m, text_ok, reply_mode)

        # локальное напоминание в TG
        if intent.start:
            remind_at = intent.start - timedelta(minutes=REMINDER_MIN)
            scheduler.add_job(
                lambda: asyncio.create_task(
                    bot.send_message(
                        OWNER_ID,
                        f"🔔 Напоминание: {event['summary']} через {REMINDER_MIN} мин.",
                    )
                ),
                trigger=DateTrigger(run_date=remind_at),
            )

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
        await send_reply(
            m,
            "Не понял запрос.\n"
            "Примеры:\n"
            "• завтра в 10:00 напомни оплатить хостинг\n"
            "• что у меня сегодня?\n"
            "• перенеси встречу с Иваном на завтра 11:30\n"
            "• удали напоминание оплатить хостинг",
            reply_mode,
        )


# ---------- ENTRY ----------
async def main():
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
