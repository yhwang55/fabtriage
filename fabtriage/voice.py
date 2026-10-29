"""Spoken sign-off notes: send a WAV recording to Muse Voice Transcribe (batch endpoint).

Engineers in the fab wear gloves; talking is easier than typing. The console records the
note in the browser as 16 kHz mono PCM16 WAV and posts it here.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid

MODEL = "muse-voice-transcribe-1.0"
URL = "https://api.meta.ai/v1/asr/transcribe"
KEYWORDS = ["DEP01-A", "DEP01-B", "DEP02-A", "DEP02-B", "CLN01", "CLN02", "MET01", "MET02", "PM", "FDC", "OOS", "OOC"]


def multipart(fields: dict, files: dict) -> tuple:
    """Build a multipart/form-data body. fields: name -> str; files: name -> (filename, bytes, type)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\nContent-Type: application/json\r\n\r\n'.encode()
            + value.encode()
            + b"\r\n"
        )
    for name, (filename, data, kind) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {kind}\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def transcribe(wav: bytes) -> dict:
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        return {"error": "MODEL_API_KEY is not set in .env"}
    if not wav.startswith(b"RIFF"):
        return {"error": "expected a WAV recording"}
    request_json = {"model": MODEL}
    if os.environ.get("VOICE_KEYWORDS", "on") == "on":
        request_json["keywords"] = KEYWORDS
    body, kind = multipart({"request": json.dumps(request_json)}, {"audio": ("note.wav", wav, "audio/wav")})
    req = urllib.request.Request(
        os.environ.get("VOICE_URL") or URL,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": kind, "Accept": "text/plain"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        if error.code == 400 and "keywords" in detail and request_json.get("keywords"):
            os.environ["VOICE_KEYWORDS"] = "off"  # the endpoint didn't take keyword biasing; retry plain
            return transcribe(wav)
        return {"error": f"Muse Voice Transcribe returned {error.code}: {detail}"}
    except (urllib.error.URLError, TimeoutError) as error:
        return {"error": f"could not reach Muse Voice Transcribe: {error}"}
    if text.startswith("{"):  # a JSON reply despite Accept: text/plain
        try:
            data = json.loads(text)
            text = data.get("transcript") or data.get("text") or text
        except ValueError:
            pass
    return {"text": text, "model": MODEL}
