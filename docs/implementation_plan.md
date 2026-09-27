# Mika-sama v1 — Implementation Plan

> **Status: approved 2026-09-27. Phase 0 in progress** (Spikes B and C done, Spike A waiting to run on the Mac; see "Phase 0 results").
> Based on [top_secret.md](top_secret.md) as of 2026-09-27. If this plan and the spec disagree, the spec wins, and this plan gets fixed.

---

## 1. Scope of v1

**In v1:** The admin types in the chatbox or speaks into the mic. Mika replies with her voice, a Live2D expression, lipsync and a transcript line, all captured by OBS. Every sentence passes through the output filter. Every turn is logged to Postgres and used as memory.

**Not in v1:** co-host, platform chat (Twitch/YouTube), singing, gaming, vision, interrupting Mika mid-reply, writing new personality traits, fine-tuning.

---

## 2. Decisions (confirmed 2026-09-27)

All defaults below were confirmed at review. Changing one later means updating the affected phase.

| # | Question | Default in this plan |
|---|----------|----------------------|
| 4 | How is intent produced? | System-set: `filter_incident` if any sentence was not ALLOW, `error_recovery` if the turn hit an error or timeout, otherwise `casual_conversation`. |
| 12 | `num_predict` | 150 (spoken replies). |
| 15 | Embedding model | `nomic-embed-text` on Ollama → `vector(768)`. |
| 17 | AI classifier times out or returns invalid output | Fail closed → REPLACE. |
| 18 | After a BLOCK, does the reply continue? | Yes: the replacement is spoken, and the next sentences keep going through the filter. |
| 19 | Writing personality traits | v1 only reads `personality_traits`. The admin can insert rows by hand. |
| 2b | Fine-tuning data source | `reply` only. |
| 20 | STT model (the spec names VAD + RMS, but not the transcription model) | `faster-whisper` on CPU (int8), `silero-vad` for voice activity, RMS as a noise gate. |
| 21 | How audio travels to the browser | WAV, base64 inside a JSON message. Simple, and fine on a local network. Can move to binary frames later. |
| 22 | Admin identity | Fixed `user_id = "admin"`. |

---

## 3. Machines, Ports, Processes

| Machine | Process | Port | Notes |
|---------|---------|------|-------|
| Mac M1 | Ollama | 11434 | `llama3.1:8b` + embedding model. `OLLAMA_NUM_PARALLEL` set from the Phase 0 spike. |
| Mac M1 | PostgreSQL + pgvector | 5432 | Local only; not exposed to the LAN. |
| Mac M1 | Server (FastAPI, `/ws/runtime`) | 8000 | Only the Acer connects. |
| Acer | Client (FastAPI, `/ws/chat`) | 8001 | Connects to the Mac as a WS client; serves `/ws/chat` to the browser. |
| Acer | Frontend (Vite dev server) | 5173 | `/avatar` (OBS browser source) and `/admin` (chatbox). |

---

## 4. Repository Layout

```
mika/
├── shared/                     # Python package, installed in both envs (pip install -e)
│   ├── enums.py                # Emotion, Intent, FilterAction
│   ├── payloads.py             # UserRequest, TurnResult, FilterResult
│   └── events.py               # All WS event models (section 5)
├── server/                     # Mac M1
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan, shutdown
│   │   ├── config.py           # LLM + server config (Python)
│   │   ├── api/ws_runtime.py
│   │   ├── llm/                # engine.py (Ollama), tag_parser.py, chunker.py
│   │   ├── filter/             # normalizer.py, hard_rules.py, ai_classifier.py, replacer.py, policy.py
│   │   ├── memory/             # cache.py (FIFO), rag.py (pgvector), history.py (prompt formatting)
│   │   ├── personality/        # engine.py (YAML + traits)
│   │   ├── state/manager.py
│   │   ├── turn/pipeline.py    # One turn end-to-end (section 6)
│   │   └── db/                 # pool.py, queries.py
│   ├── data/                   # personality.yaml, prohibited_words.txt
│   ├── scripts/setup_db.sql
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── client/                     # Acer
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py           # SERVER_WS_URL, VOICE_MODEL, REF_VOICE_PATH, REF_TEXT
│   │   ├── api/ws_chat.py      # Browser bridge
│   │   ├── ws/connector.py     # Client of /ws/runtime (reconnects)
│   │   ├── tts/engine.py       # GenieTTS
│   │   ├── stt/                # vad.py, engine.py, gate.py (half-duplex mute)
│   │   └── features/           # Empty in v1
│   ├── tests/
│   └── requirements.txt
└── frontend/                   # React + TS + Vite
    └── src/
        ├── pages/AvatarPage.tsx, AdminPage.tsx
        ├── components/Live2DStage.tsx, TranscriptOverlay.tsx, Chatbox.tsx
        ├── audio/playbackQueue.ts, lipsync.ts
        ├── services/chatSocket.ts
        └── types/events.ts     # Mirrors shared/events.py
```

The Live2D model is copied from `others/2D/miku_pro/runtime/` into `frontend/public/models/`, along with the new `.exp3.json` files.

---

## 5. Event Contracts

These are the most important part of the plan. Every message is JSON with a `type` field and a `turn_id` wherever it belongs to a reply.

### 5.1 `/ws/runtime` (Acer ⇄ Mac)

| Direction | `type` | Fields | Meaning |
|-----------|--------|--------|---------|
| Acer → Mac | `user_message` | `user_id`, `message`, `source` (`chat` / `voice`) | The only request payload. |
| Acer → Mac | `client_status` | `status`, `detail` | Health updates (TTS ready, STT ready…). |
| Mac → Acer | `turn_start` | `turn_id`, `emotion` | Sent as soon as the emotion tag is parsed. |
| Mac → Acer | `sentence` | `turn_id`, `seq`, `text`, `action` | One approved sentence, in order. |
| Mac → Acer | `turn_end` | `turn_id`, `last_seq`, `intent` | No more sentences for this turn. |
| Mac → Acer | `error` | `turn_id`, `message` | The turn failed; the Acer unmutes STT. |

### 5.2 `/ws/chat` (Browser ⇄ Acer)

| Direction | `type` | Fields | Meaning |
|-----------|--------|--------|---------|
| Admin page → Acer | `admin_message` | `message` | The Acer wraps it as `user_message` with `user_id = "admin"`. |
| Acer → Avatar page | `emotion` | `turn_id`, `emotion` | Switch expression. |
| Acer → Avatar page | `audio_chunk` | `turn_id`, `seq`, `text`, `audio_b64`, `sample_rate` | One spoken sentence. |
| Acer → Avatar page | `turn_end` | `turn_id`, `last_seq` | So the page knows when the reply is complete. |
| Avatar page → Acer | `playback_started` | `turn_id`, `seq` | |
| Avatar page → Acer | `playback_finished` | `turn_id`, `seq` | When `seq == last_seq`, the Acer unmutes STT. |
| Acer → Admin page | `transcript` | `role` (`admin` / `mika`), `text` | Chat log shown in the admin page. |

---

## 6. One Turn on the Mac

```
user_message
  → build prompt: personality YAML + active traits + FIFO history + RAG context + user message
  → Ollama stream (llama3.1:8b)
  → tag parser: read "[emotion]", validate, fallback neutral → send turn_start
  → normalizer → sentence chunker (flush the buffer at end of stream)
  → for each sentence, in order:
        hard rules hit?   → BLOCK: replacer (2nd llama3.1:8b call) → re-check with filter
                                   → still unsafe or timeout → toast line
        else classifier   → safe → ALLOW
                            unsafe / timeout / bad output → REPLACE ("Filtered" + toast)
        → send sentence(seq, text, action)
  → send turn_end(intent)
  → save to DB: chat_logs row + memory_embeddings row; push to FIFO cache
```

Details:
- **Classifier call:** temperature 0, Ollama structured output (`format` = JSON schema `{safe: bool, reason: str}`). The input is the user message, the last few history turns, the reply so far and the sentence being judged. It has a strict timeout.
- **Replacer call:** it gets the user message, the reply so far and the block reason, and must return one sentence. It has a strict timeout and is re-filtered once. There is no retry loop.
- **Order:** sentences are filtered one at a time per turn, so `seq` order is always the spoken order. The LLM keeps streaming into a bounded queue while the filter works.
- **History formatting (decision #2):** an ALLOW turn is stored as a normal assistant message. For a turn with REPLACE or BLOCK, the assistant message is `reply`, followed by a note containing `original_reply` and the action.
- **Shutdown:** all turn tasks live in an `asyncio.TaskGroup`. Queues are bounded. `CancelledError` is always re-raised. WS handlers exit on disconnect, and the lifespan cancels and awaits everything.

---

## 7. Phases

Each phase ends with a check that proves it works.

### Phase 0 — Setup and spikes (go/no-go for the design)
1. `git init`, `.gitignore` (models, `.env`, logs, `node_modules`), push to GitHub.
2. Conda envs with Python 3.11.9 on both machines; Node LTS on the Acer.
3. **Spike A (most important):** on the M1, measure `llama3.1:8b` time to the first sentence, and the time to classify one sentence *while the main stream is still running*. Test with `OLLAMA_NUM_PARALLEL=1` and `2`, and watch memory. With 1, the classifier waits for the whole reply to finish, so per-sentence filtering during streaming only works with 2 or more.
4. **Spike B:** on the Acer, measure GenieTTS time per sentence with `mikav3_onnx_model` + `55.wav`/`55.txt`. It must be faster than real time.
5. **Spike C:** render `miku_sample_t04` in a bare Vite page (PixiJS + a Live2D Cubism 4 loader + Cubism Core, which is downloaded from Live2D under its own license). Confirm the versions work together, and that `ParamMouthOpenY` can be driven from code.
- **Done when:** the numbers from A and B are written into this file, and C shows the model on screen. If A is too slow, pick a fallback before Phase 3: a larger classifier timeout, or generating the full reply first and then filtering sentences while earlier ones are already being spoken.

#### Phase 0 results

| Step | Status | Result |
|------|--------|--------|
| 1. Git | Done | [github.com/OnicronPandora/mika_sama_v1](https://github.com/OnicronPandora/mika_sama_v1). Work is pushed to `dev-mode`, and the admin merges it into `main` through a pull request. `.gitignore` = GitHub's Python template + project rules. |
| 2. Environments | Acer done, Mac pending | Acer: `.conda` (Python 3.11.9 from conda-forge), Node 24.12, npm 11.7. Mac: commands in [spikes/README.md](../spikes/README.md). |
| A. Ollama on the M1 | **Waiting: run on the Mac** | Script ready and tested against Ollama 0.34.2 on the Acer (`llama3:latest` on CPU; those timings don't represent the M1). |
| B. GenieTTS on the Acer | Done | Median real-time factor **0.89**: keeps up, with about 10% headroom. |
| C. Live2D in the browser | Done | Model renders; lipsync driven by audio volume works. |

**Spike B (Acer, i5-12450H, 16 GB):** [full table](../spikes/spike_b_tts/results/acer.md)
- genie-tts 2.0.2, onnxruntime 1.22.1 (CPU only), model type V2ProPlus. Output is 16-bit mono PCM at 32 kHz.
- Loading the model and reference audio takes 10.8 s, so it happens once at client startup.
- Synthesis takes 1.5 s for a 2-word sentence and up to 4.8 s for 17–21 words. Long sentences run at a real-time factor of 0.85–0.91. Short ones are slower than real time (1.23 for "Hi everyone!", 1.04 for 5 words) because each call has a fixed overhead.
- What this means:
  - The Acer only keeps up if nothing else competes for the CPU. OBS must use the Intel Quick Sync hardware encoder, not x264 (Phase 10). STT stays muted while Mika speaks (already decided).
  - The Acer must synthesize sentence N+1 while sentence N plays (Phase 7).
  - Time until Mika starts speaking = the Mac's approval time (Spike A) + 1.5–3 s of synthesis.
- GenieTTS details for Phase 7:
  - Set `GENIE_DATA_DIR` before importing it; otherwise it blocks on an `input()` prompt.
  - Its player always opens a sounddevice output stream, even with `play=False`.
  - `tts_async` waits on `asyncio.Queue.get()` with no timeout, so wrap it in `asyncio.timeout()`. This is a likely source of the old deadlock.
  - The player is a global singleton, so only one synthesis runs at a time.

**Spike C (Acer, built-in Chromium browser):**
- Working stack: **easy-live2d 1.0.0 + PixiJS 8.21 (WebGL 2) + Cubism Core 6.0.1 from the Cubism SDK for Web R5**, served by Vite 8.
- The Core file on Live2D's CDN (`cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js`) is version 5.1.0, and easy-live2d 1.0.0 rejects it. The Core has to come from the R5 SDK zip.
- The model loads with 8 motions (Idle ×3, Tap ×2, Flick ×2, FlickUp ×1), no expressions, and `ParamMouthOpenY` ranging 0–1. The transparent background works.
- `setParameterValueById` values persist and are applied after motions, expressions and physics on every frame. That matters: all 8 motions animate `ParamMouthOpenY` themselves, and the override still wins while a motion plays.
- Lipsync verified: a 5.1 s GenieTTS clip played through Web Audio. An `AnalyserNode` RMS value × 6 drives `ParamMouthOpenY`. The mouth follows the speech, closes on pauses, and resets to 0 at the end.
- Notes for later phases:
  - Phase 8: motions also animate `ParamMouthForm`, so expressions that change the mouth shape should use the Overwrite blend.
  - Phase 9: a gain of 6 hits 1.0 at peaks, so tune the gain and smoothing. The override keeps its last value, so set it to 0 when audio ends. Idle motions then can't move the mouth, which is intended.
  - Phase 10: confirm OBS's browser source supports WebGL 2.

**Spike A dry-run findings** (Acer, `llama3:latest`; functional check only):
- The JSON-schema classifier returned valid output in 6/6 calls.
- Emotion tag: 2/4 replies valid. Both misses began with a bare word and no brackets (`Happy Ah, I'm feeling…`), so "Happy" would have been spoken. `[Happy]` in capitals parsed fine. Phase 3 now covers this (below). The Mac run with `llama3.1:8b` will give the real rate.

### Phase 1 — Shared contracts
- Enums, payloads and every event from section 5 as Pydantic v2 models, plus the same types in `frontend/src/types/events.ts`.
- **Done when:** round-trip tests (model → JSON → model) pass for every event.

### Phase 2 — Database and config
- `setup_db.sql` with the schema from the spec (`vector(768)` per decision #15), plus indexes on `chat_logs(user_id, created_at)` and a vector index on `memory_embeddings`.
- `AsyncConnectionPool` opened and closed in the lifespan; the pgvector adapter registered; `.env.example`.
- **Done when:** the script runs on a clean database, and a test inserts and reads back a `chat_logs` row and a nearest-neighbour search.

### Phase 3 — LLM core
- Personality loader (YAML + active traits), Ollama async streaming client (one shared client, reused per request), emotion tag parser, normalizer, sentence chunker.
- **Done when:** unit tests pass for the tag parser (missing, invalid, split across tokens, different capitalization, and a bare leading emotion word such as `Happy Ah, …`, which must be stripped so it isn't spoken) and the chunker (abbreviations, decimals, "...", end of stream). A script prints a live reply as tagged sentences.

### Phase 4 — Output filter
- Hard rules (word-boundary matching after normalization), AI classifier, replacer, policy engine producing `FilterResult`.
- **Done when:** tests with a fake LLM cover ALLOW, REPLACE, BLOCK, a replacement that is itself unsafe, a classifier timeout, and invalid classifier JSON.

### Phase 5 — Memory, state, prompt builder
- FIFO cache (bounded), RAG retrieval, history formatter (decision #2), state manager (`Field(default_factory=dict)`), intent rule (decision #4).
- **Done when:** a test builds the full prompt for a user with past filtered turns, and the output matches the expected text.

### Phase 6 — Server wiring
- Turn pipeline (section 6), `/ws/runtime` with an `Origin` check, lifespan startup and shutdown, `server.log`.
- **Done when:** an integration test drives the server with a fake Acer WS client and a fake LLM through a full turn, *and* Ctrl+C during a turn shuts the server down within a few seconds (regression test for known issues #1 and #2).

### Phase 7 — Acer client
- `/ws/runtime` connector with reconnect, GenieTTS worker (in a thread so it doesn't block the event loop), `/ws/chat` bridge, STT (VAD + RMS gate + faster-whisper), half-duplex gate driven by `turn_start` / `playback_finished` / `error`.
- The TTS worker synthesizes the next sentence while the current one plays, and applies the GenieTTS details from the Phase 0 results.
- **Done when:** with the real server, a typed message produces `audio_chunk` events in order, and speaking into the mic sends a `user_message`. The mic stays muted until the last `playback_finished` arrives.

### Phase 8 — Live2D expressions
- Write `happy`, `sad`, `confused`, `angry` and `neutral` `.exp3.json` using `ParamEyeLSmile/RSmile`, `ParamBrow*`, `ParamMouthForm`, `ParamCheek` (never `ParamMouthOpenY`), and register them in `model3.json`. Use the Overwrite blend for `ParamMouthForm`, because the motions animate it too.
- **Done when:** each expression shows correctly in the browser, and lipsync still moves the mouth with each expression active.

### Phase 9 — Frontend
- Stack from Spike C: easy-live2d 1.0.0 + PixiJS 8 + Cubism Core from the SDK for Web R5 (git-ignored; each machine downloads it under Live2D's license). Reuse the Spike C lipsync code.
- `/avatar`: Live2D stage, expression switching, audio playback queue (in `seq` order), lipsync from a Web Audio `AnalyserNode` → `ParamMouthOpenY`, transcript line shown when its audio starts, `playback_*` events.
- `/admin`: chatbox + transcript log.
- A "click to enable audio" overlay for normal Chrome (OBS doesn't need it).
- **Done when:** a typed message makes Mika change expression, speak with moving lips, and show the transcript, in normal Chrome.

### Phase 10 — OBS and end to end
- OBS browser source → `http://localhost:5173/avatar`, transparent background, "Control audio via OBS" on. Confirm WebGL 2 works in the browser source.
- OBS output uses the Intel Quick Sync (QSV) hardware encoder, so encoding doesn't take CPU away from GenieTTS (Spike B).
- **Done when:** a 15-minute session (typed and spoken) runs with no stuck turns, no Mika transcribing her own voice, and a clean shutdown of both machines.

---

## 8. Testing Approach

| Level | What | How |
|-------|------|-----|
| Unit | Tag parser, normalizer, chunker, hard rules, policy, history formatter, intent rule | pytest, no network |
| Component | Filter + turn pipeline | pytest with a scripted fake LLM (fixed token streams, forced timeouts) |
| Integration | Server ⇄ fake Acer; Acer ⇄ fake server | pytest + real WebSockets on localhost |
| Manual | Audio, lipsync, OBS, mic | Checklist at the end of Phases 9 and 10 |

---

## 9. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The M1 can't run the reply stream and the classifier in parallel (memory or speed) | Long silence before Mika speaks | Spike A in Phase 0, before any filter code is written |
| One classifier call per sentence, plus the replacer on BLOCK, all on the same 8B model | Latency (accepted) | Measure it in Spike A; keep strict timeouts |
| GenieTTS only just keeps up on the Acer's CPU (Spike B: real-time factor 0.89) | Gaps between sentences if anything else uses the CPU | Synthesize ahead while the previous sentence plays; OBS on the Quick Sync hardware encoder; STT muted while Mika speaks; later, try more onnxruntime threads or a GPU provider |
| `original_reply` in the prompt context (decision #2) | The LLM may repeat filtered content | Track the `filter_incident` rate in `chat_logs` |
| Cubism Core license and PixiJS/Live2D library versions | Frontend blocked | Resolved by Spike C: easy-live2d 1.0.0 + PixiJS 8 + R5 Core work together |
| easy-live2d 1.0.0 is a very new major release (published 2026-09-24) | Bugs in the library | Pin the exact version. Untested fallbacks: easy-live2d 0.4.4 with an older Core (the library's documented option), or pixi-live2d-display |
| Browser autoplay rules | No audio in normal Chrome | Click-to-enable overlay; OBS is not affected |
