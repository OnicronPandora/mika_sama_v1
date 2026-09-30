# Mika-sama v1 — Implementation Plan

> **Status: approved 2026-09-27. Phases 0–2 complete** (spikes; shared contracts; database and config). Next: Phase 3.
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
| Mac M1 | Ollama | 11434 | `llama3.1:8b` only. `OLLAMA_NUM_PARALLEL=1`: the 8 GB M1 has no memory for a second slot (Spike A). Embeddings run on the CPU inside the server process (#23). |
| Mac M1 | PostgreSQL + pgvector | 5432 | Local only; not exposed to the LAN. |
| Mac M1 | Server (FastAPI, `/ws/runtime`) | 8000 | Only the Acer connects. |
| Acer | Client (FastAPI, `/ws/chat`) | 8001 | Connects to the Mac as a WS client; serves `/ws/chat` to the browser. |
| Acer | Frontend (Vite dev server) | 5173 | `/avatar` (OBS browser source) and `/admin` (chatbox). |

---

## 4. Repository Layout

```
mika/
├── shared/                     # Package "mika-shared", installed in both envs (pip install -e mika/shared)
│   ├── pyproject.toml
│   ├── mika_shared/
│   │   ├── base.py             # Contract base model (immutable, unknown fields rejected), field types
│   │   ├── enums.py            # Emotion, Intent, FilterAction + the small enums the events use
│   │   ├── payloads.py         # UserRequest, FilterResult, TurnResult
│   │   ├── events.py           # All WS event models (section 5) + one parser per channel direction
│   │   └── codegen_ts.py       # Writes frontend/src/types/events.ts from the models
│   └── tests/
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
│   │   └── db/                 # pool.py, schema.py, queries.py
│   ├── data/                   # personality.yaml, prohibited_words.txt
│   ├── scripts/                # setup_db.sql; setup_wsl_test_db.sh (Acer test database)
│   ├── tests/
│   ├── requirements.txt, requirements-dev.txt, pytest.ini
│   ├── README.md               # Setup on the Mac, test database on the Acer
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
        └── types/events.ts     # Generated from mika_shared (do not edit by hand)
```

The Live2D model is copied from `others/2D/miku_pro/runtime/` into `frontend/public/models/`, along with the new `.exp3.json` files.

---

## 5. Event Contracts

These are the most important part of the plan. Every message is JSON with a `type` field and a `turn_id` wherever it belongs to a reply. The code lives in `mika/shared/mika_shared/events.py` (Phase 1); if a table below and the code disagree, fix one of them in the same change.

Common rules: `seq` is 0-based. Text fields must not be blank (surrounding whitespace is trimmed). Turn ids are 1–64 characters of `A–Z a–z 0–9 _ -`. Unknown fields are rejected.

### 5.1 `/ws/runtime` (Acer ⇄ Mac)

| Direction | `type` | Fields | Meaning |
|-----------|--------|--------|---------|
| Acer → Mac | `user_message` | `user_id`, `message`, `source` (`chat` / `voice`) | The only request payload. |
| Acer → Mac | `client_status` | `component` (`tts` / `stt` / `avatar_page` / `admin_page`), `status` (`starting` / `ready` / `error` / `stopped`), `detail` (optional) | Health updates (TTS ready, STT ready…). |
| Mac → Acer | `turn_start` | `turn_id`, `emotion` | Sent as soon as the emotion tag is parsed. |
| Mac → Acer | `sentence` | `turn_id`, `seq`, `text`, `action` | One approved sentence, in order. |
| Mac → Acer | `turn_end` | `turn_id`, `last_seq` (null if the turn produced no sentences), `intent` | No more sentences for this turn. |
| Mac → Acer | `error` | `turn_id` (null if not tied to a turn), `message` | The turn failed; the Acer unmutes STT. |

### 5.2 `/ws/chat` (Browser ⇄ Acer)

| Direction | `type` | Fields | Meaning |
|-----------|--------|--------|---------|
| Admin page → Acer | `admin_message` | `message` | The Acer wraps it as `user_message` with `user_id = "admin"`. |
| Acer → Avatar page | `emotion` | `turn_id`, `emotion` | Switch expression. |
| Acer → Avatar page | `audio_chunk` | `turn_id`, `seq`, `text`, `audio_b64`, `sample_rate` | One spoken sentence. |
| Acer → Avatar page | `turn_end` | `turn_id`, `last_seq` (null if the turn produced no sentences) | So the page knows when the reply is complete. |
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
| 2. Environments | Done | Acer: `.conda` (Python 3.11.9 from conda-forge), Node 24.12, npm 11.7. Mac: set up from [spikes/README.md](../spikes/README.md) and used for Spike A. |
| A. Ollama on the M1 | Done | The 8 GB M1 serves **one request at a time**. The first sentence is approved after a median of 5.8 s (4.1–9.4 s). Accepted under decision #1, so no fallback is needed. |
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

**Spike A (Mac M1, 8 GB RAM, macOS 26.6, Ollama 0.34.0, `llama3.1:8b` Q4_K_M):** [parallel-1](../spikes/spike_a_ollama/results/parallel-1.md), [parallel-2](../spikes/spike_a_ollama/results/parallel-2.md)
- Memory: the model takes 5.29 GB, and only 4.32 GB of it fits on the GPU, so about 1 GB runs on the CPU. Context length is 4096 tokens. Generation runs at 10.5–12.5 tokens/s, and loading the model takes 6–7 s.
- **Requests are served one at a time**, including in the `OLLAMA_NUM_PARALLEL=2` run:
  - The script's own check reported "inconclusive" for all 10 runs, because Mika's replies were short (19–58 tokens; the stream finished after a median of 3.6 s).
  - The raw timings settle it: a classification sent while the reply was still streaming took about (remaining stream time + its usual 2–3 s). Example: in `parallel-2` run 2 it was sent 2.5 s before the stream ended and took 4.1 s, against 1.9 s when run alone.
  - Memory stayed at 5.29 GB with `OLLAMA_NUM_PARALLEL=2`. A second slot would add about 0.5 GB, so it was most likely never allocated, and the 8 GB Mac has no room for one anyway. **Decision: `OLLAMA_NUM_PARALLEL=1`.**
- Latency, medians over all 10 runs:
  - First sentence ready: 2.5 s.
  - First sentence approved: 5.8 s (4.1–9.4 s).
  - Each further sentence: about 2.4 s after the previous one.
  - Replacer: about 2.6 s.
- **Time until Mika starts speaking** = first approval + GenieTTS for the first sentence (1.5–3 s, Spike B) ≈ **8 s typical, 6–12 s range.** Accepted under decision #1.
- After the first sentence, the next one is approved about 2.4 s later, while the previous one is still playing (3–5 s), so there are no gaps. The exception is right after very short sentences (under about 2.4 s of audio, such as "Hi everyone!").
- The emotion tag was valid in **20/20** replies, and classifier JSON in **28/28** calls. In the earlier Acer dry-run with `llama3`, 2 of 4 replies began with a bare word (`Happy Ah, …`). That didn't happen with `llama3.1:8b`, but Phase 3 keeps the test.
- Most of each classifier call goes into generating its free-text `reason` at about 11 tokens/s.

Ways to cut the latency later (measured options, not decided):
- Phase 3: merge sentences shorter than about 6 words into the next one. That means fewer classifier calls, less TTS overhead (short sentences run slower than real time, Spike B), and fewer pauses.
- Phase 4: have the classifier return `reason` as a short code (`ok`, `sexual`, `violence`, `hate`, `self_harm`, `personal_info`, `other`) instead of free text. That should save about 1 s per sentence; measure it in Phase 4.
- Later: let the Acer synthesize the first sentence while the Mac is still classifying it, and play it only if approved. That saves 1.5–3 s, but needs a contract change and sends unapproved text to the Acer.

### Phase 1 — Shared contracts ✅ (2026-09-27)
- Enums, payloads and every event from section 5 as Pydantic v2 models, plus the same types in `frontend/src/types/events.ts`.
- **Done when:** round-trip tests (model → JSON → model) pass for every event.
- **Result:** package `mika-shared` in `mika/shared` ([README](../mika/shared/README.md)). 41 tests pass: a JSON round trip for all 13 events, the per-channel event sets against section 5, rejection of wrong-direction/unknown/invalid events, and the `FilterResult` rules. The TypeScript types are generated from the Python models, and a test fails if the committed file is out of date. `tsc --strict` compiles them, with exhaustive `switch` narrowing on `type`.
- Semantics fixed along the way (also in section 5): `client_status` names its `component`; `turn_end.last_seq` is null for a turn with no sentences; `error.turn_id` is null for errors outside a turn; a turn's `action` is its most severe sentence action (BLOCK over REPLACE over ALLOW); an ALLOW `FilterResult` has no `filter_response`, and REPLACE/BLOCK must have one.

### Phase 2 — Database and config ✅ (2026-09-30)
- `setup_db.sql` with the schema from the spec (`vector(768)` per decision #15), plus indexes on `chat_logs(user_id, created_at)` and a vector index on `memory_embeddings`.
- `AsyncConnectionPool` opened and closed in the lifespan; the pgvector adapter registered; `.env.example`.
- **Done when:** the script runs on a clean database, and a test inserts and reads back a `chat_logs` row and a nearest-neighbour search.
- **Result:** [mika/server](../mika/server/README.md). 24 tests pass against PostgreSQL 16 + pgvector 0.6.0 in WSL on the Acer. Each database test gets a fresh schema, so the script is proven on a clean database every run. The tests cover:
  - the tables, indexes and `vector(768)` column; re-running the script;
  - the CHECK constraints against the shared enums;
  - a `chat_logs` round trip; the user interaction count; the foreign keys;
  - nearest-neighbour order and the embedding-size checks;
  - opening and closing the pool in the lifespan; `/health`.
- Also checked by hand: `python -m app.db.schema` against `mika_dev`, and `uvicorn app.main:app` answering `/health` with the database OK.
- Choices made here:
  - Enum columns are `TEXT` with CHECK constraints (easier to extend than PostgreSQL enum types).
  - `session_id` is a `UUID`; `chat_logs.id` is a `BIGINT` identity.
  - The vector index is HNSW with cosine distance.
  - `personality_traits.source_chat_log_id` is null for traits the admin adds by hand.
  - `touch_user` creates a user on first contact and counts each interaction.
  - Tests only touch `TEST_DB_NAME`.
- Verified on the Mac (2026-09-30): the tests pass against the EnterpriseDB PostgreSQL 18 with pgvector 0.8.6 built from source (see the server README). The Acer's WSL test database has pgvector 0.6.0 from Ubuntu; the features used here work on both.

### Phase 3 — LLM core
- Personality loader (YAML + active traits), Ollama async streaming client (one shared client, reused per request), emotion tag parser, normalizer, sentence chunker.
- **Done when:** unit tests pass for the tag parser (missing, invalid, split across tokens, different capitalization, and a bare leading emotion word such as `Happy Ah, …`, which must be stripped so it isn't spoken) and the chunker (abbreviations, decimals, "...", end of stream). A script prints a live reply as tagged sentences.

### Phase 4 — Output filter
- Hard rules (word-boundary matching after normalization), AI classifier, replacer, policy engine producing `FilterResult`.
- **Done when:** tests with a fake LLM cover ALLOW, REPLACE, BLOCK, a replacement that is itself unsafe, a classifier timeout, and invalid classifier JSON.

### Phase 5 — Memory, state, prompt builder
- FIFO cache (bounded), RAG retrieval, history formatter (decision #2), state manager (`Field(default_factory=dict)`), intent rule (decision #4).
- The whole prompt, plus room for `num_predict`, must fit in the 4096-token context (Spike A). A longer context needs memory the 8 GB Mac doesn't have.
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
| The 8 GB M1 serves one request at a time (Spike A) | Mika starts speaking about 8 s after a message (6–12 s) | Accepted (decision #1). The latency options in the Phase 0 results can cut it later |
| The 8 GB M1 is at its memory limit (model 5.29 GB, about 1 GB already on the CPU) | Loading the embedding model through Ollama may unload `llama3.1:8b` (6–7 s reload on the next message) | Resolved (#23): embeddings run on the CPU inside the server process. Pick the library in Phase 5 and check its memory use |
| One classifier call per sentence, plus the replacer on BLOCK, all on the same 8B model | Latency (accepted) | Measure it in Spike A; keep strict timeouts |
| GenieTTS only just keeps up on the Acer's CPU (Spike B: real-time factor 0.89) | Gaps between sentences if anything else uses the CPU | Synthesize ahead while the previous sentence plays; OBS on the Quick Sync hardware encoder; STT muted while Mika speaks; later, try more onnxruntime threads or a GPU provider |
| `original_reply` in the prompt context (decision #2) | The LLM may repeat filtered content | Track the `filter_incident` rate in `chat_logs` |
| Cubism Core license and PixiJS/Live2D library versions | Frontend blocked | Resolved by Spike C: easy-live2d 1.0.0 + PixiJS 8 + R5 Core work together |
| easy-live2d 1.0.0 is a very new major release (published 2026-09-24) | Bugs in the library | Pin the exact version. Untested fallbacks: easy-live2d 0.4.4 with an older Core (the library's documented option), or pixi-live2d-display |
| Browser autoplay rules | No audio in normal Chrome | Click-to-enable overlay; OBS is not affected |
