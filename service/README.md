# VoicePay Backend Service

## Run locally

1. Install dependencies:

```bash
pip install -r service/requirements.txt
```

2. Start API:

```bash
uvicorn service.app:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

- `POST /transcribe`
- `POST /pay/plan`
- `POST /pay/execute`

## Environment variables

- `STRIPE_SECRET_KEY`: optional; if missing, execution falls back to mock mode.
- `CACTUS_TRANSCRIBE_MODULE`: optional import path exposing `transcribe(audio_base64)`.
