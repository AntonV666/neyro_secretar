from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from google_auth_oauthlib.flow import Flow
from dotenv import load_dotenv   # <<< добавить импорт
import os, json

load_dotenv()  # <<< ВАЖНО: подгружаем .env

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"   # DEV-режим: разрешить http://localhost


app = FastAPI()

@app.get("/oauth/google")
async def start_google():
    flow = Flow.from_client_secrets_file(
        "client_secret.json",
        scopes=["https://www.googleapis.com/auth/calendar"],
        redirect_uri=os.getenv("GOOGLE_REDIRECT_URI"),
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    with open(".oauth_state", "w") as f:
        f.write(state)
    return PlainTextResponse(auth_url)


@app.get("/oauth/google/callback")
async def google_callback(request: Request):
    with open(".oauth_state") as f:
        state = f.read()
    flow = Flow.from_client_secrets_file(
        "client_secret.json",
        scopes=["https://www.googleapis.com/auth/calendar"],
        state=state,
        redirect_uri=os.getenv("GOOGLE_REDIRECT_URI"),
    )
    flow.fetch_token(authorization_response=str(request.url))
    creds = flow.credentials
    with open("google_token.json", "w") as f:
        f.write(creds.to_json())
    return PlainTextResponse("Google OAuth OK. Token сохранён.")
