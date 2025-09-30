# app/stt.py
import subprocess
import os
from vosk import Model, KaldiRecognizer
import wave
import json

_model = None


def _ensure_model(path: str):
    global _model
    if _model is None:
        _model = Model(path)


def _ogg_to_wav(in_path: str, out_path: str):
    subprocess.run(
        ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_path],
        check=True
    )


def transcribe_voice(ogg_path: str, model_path: str | None = None) -> str:
    mp = model_path or os.getenv("VOSK_MODEL_PATH", "/models/vosk-ru")
    _ensure_model(mp)

    wav_path = ogg_path.replace(".ogg", ".wav")
    _ogg_to_wav(ogg_path, wav_path)

    wf = wave.open(wav_path, "rb")
    rec = KaldiRecognizer(_model, wf.getframerate())

    text = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            j = json.loads(rec.Result())
            text.append(j.get("text", ""))

    j = json.loads(rec.FinalResult())
    text.append(j.get("text", ""))

    return " ".join(t for t in text if t).strip()
