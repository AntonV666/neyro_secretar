# Dockerfile
FROM python:3.12-slim

# Системные пакеты: ffmpeg (для STT/TTS), tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tzdata curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Создадим непривилегированного пользователя
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# Ставим зависимости отдельно — кешируем слой
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копируем код
COPY app /app/app

# Папки под временные файлы
RUN mkdir -p /app/tmp /app/tmp_tts
RUN chown -R appuser:appuser /app
USER appuser

# Переменные окружения по умолчанию
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Yekaterinburg \
    SERVICE=bot

# Энтрипойнт-скрипт: переключение между bot / oauth
COPY --chown=appuser:appuser <<'EOS' /app/entrypoint.sh
#!/usr/bin/env bash
set -e

# Подсказка: google_token.json и client_secret.json ожидаются в /app/
# (см. docker-compose.yml — туда их монтируем)

if [ "$SERVICE" = "oauth" ]; then
  # В проде HTTPS! Не выставляйте OAUTHLIB_INSECURE_TRANSPORT на сервере.
  exec uvicorn app.oauth_server:app --host 0.0.0.0 --port 8080
else
  # bot — основной сервис
  exec python -m app.main
fi
EOS
RUN chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD bash -c '[ "$SERVICE" = "oauth" ] && wget -qO- 127.0.0.1:8080/oauth/google >/dev/null || echo ok'

CMD ["/app/entrypoint.sh"]
