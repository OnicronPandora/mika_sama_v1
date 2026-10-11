# Mika-sama client (Acer)

The Acer's side: input and output only ([implementation plan](../../docs/implementation_plan.md), Phase 7). It
connects to the Mac's `/ws/runtime` and keeps reconnecting, forwards what Pandora types or says, speaks Mika's
approved sentences with GenieTTS, and serves the browser pages on `/ws/chat`:
- the avatar page (`ws://127.0.0.1:8001/ws/chat?page=avatar`, in OBS or Chrome) gets Mika's emotion, one audio
  chunk per sentence (a WAV file, base64) and the end of each reply, and reports when each chunk starts and
  finishes playing;
- the admin page (`?page=admin`) sends typed messages and gets the transcript and notices (for example when
  the Mac can't be reached).

While Mika answers, the microphone is muted: from Pandora's message until the avatar page reports that Mika's
last sentence finished playing, plus half a second (half-duplex, so Mika never hears herself). Without an avatar
page, or if it stops reporting, the mic opens again after the reply's length plus 10 s.

## Setup (in the project's `.conda` env, from the repo root)

```bash
pip install -e mika/shared
pip install -r mika/client/requirements-dev.txt
```

The voice files live in `others/voice` (git-ignored): `mikav3_onnx_model`, `ref_data/55.wav` with `55.txt`, and
`GenieData`. The first start downloads Whisper `small.en` (486 MB) into `mika/client/.cache/whisper`
(git-ignored).

## Run

```bash
cd mika/client
python -m app
```

It reaches the Mac at `ClientSettings.server_ws_url` in `app/config.py`
(`ws://Pandoras-MacBook-Pro.local:8000/ws/runtime`); start the server on the Mac before or after, since the
client keeps retrying. Loading GenieTTS and Whisper takes about 15 s after the start. Logs go to `client.log`
and the console; Ctrl+C stops it. `http://127.0.0.1:8001/health` shows the Mac connection, how the voice,
listening and pages are doing, and whether the microphone is open.

## Check the microphone

```bash
python -m app.stt.check
```

It prints the microphone's level and speech probability twice a second, and what Whisper hears; nothing is
sent to the Mac. When you speak, "level" should be well above `ListenSettings.rms_gate` (0.005); in a quiet
room, below it. `--file recording.wav` listens to a 16-bit WAV file instead.

## Tests

```bash
cd mika/client
pytest
```

`MIKA_TEST_VOICE=1` and `MIKA_TEST_STT=1` also run the tests that use the real GenieTTS and Whisper.
