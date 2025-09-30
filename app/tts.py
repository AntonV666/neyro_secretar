# app/tts.py
import os
import asyncio
from pathlib import Path
import uuid

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "auto").lower()  # auto -> edge с fallback на gTTS
TTS_VOICE = os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural")
TTS_LANG = os.getenv("TTS_LANG", "ru")


# ---------- Edge TTS (async) ----------
async def _edge_tts_synthesize(text: str, out_path_mp3: Path, voice: str):
    import edge_tts  # pip install edge-tts
    communicate = edge_tts.Communicate(text, voice=voice, rate="+0%", volume="+0%")
    await communicate.save(str(out_path_mp3))


# ---------- gTTS (sync, завернём в thread) ----------
def _gtts_synthesize_sync(text: str, out_path_mp3: Path, lang: str):
    from gtts import gTTS  # pip install gTTS
    tts = gTTS(text=text, lang=lang)
    tts.save(str(out_path_mp3))


async def _gtts_synthesize(text: str, out_path_mp3: Path, lang: str):
    # чтобы не блокировать event loop
    await asyncio.to_thread(_gtts_synthesize_sync, text, out_path_mp3, lang)


# ---------- MP3 -> OGG (voice) ----------
async def _mp3_to_ogg_voice(mp3_path: Path, ogg_path: Path):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", str(mp3_path),
        "-c:a", "libopus",
        "-b:a", "64k",
        "-ar", "48000",
        "-ac", "1",
        str(ogg_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg конвертация в OGG не удалась")


async def synthesize_tts_async(text: str, out_dir: str = "./tmp_tts") -> Path:
    """
    Асинхронно синтезирует речь:
    - provider=edge → MP3 → OGG
    - при ошибке edge и в режиме auto → fallback на gTTS
    Возвращает путь к OGG (для отправки как voice).
    """
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    base = uuid.uuid4().hex
    mp3_path = out_dir_path / f"{base}.mp3"
    ogg_path = out_dir_path / f"{base}.ogg"

    last_err = None

    async def _do_edge():
        await _edge_tts_synthesize(text, mp3_path, TTS_VOICE)
        await _mp3_to_ogg_voice(mp3_path, ogg_path)
        return ogg_path

    async def _do_gtts():
        await _gtts_synthesize(text, mp3_path, TTS_LANG)
        await _mp3_to_ogg_voice(mp3_path, ogg_path)
        return ogg_path

    if TTS_PROVIDER in ("edge", "auto"):
        try:
            return await _do_edge()
        except Exception as e:
            last_err = e
            # если не auto — пробрасываем
            if TTS_PROVIDER == "edge":
                raise

    # fallback на gTTS (auto) или явный gtts
    if TTS_PROVIDER in ("gtts", "auto"):
        try:
            return await _do_gtts()
        except Exception as e:
            last_err = e

    raise RuntimeError(f"TTS synth failed. Last error: {last_err}")


