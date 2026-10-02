### System Requirement Specification

> This is the authoritative spec. Where another file in `docs/` conflicts with it, this file wins.
> Last updated: 2026-09-27 (design decisions folded in, see "Decision log" at the bottom).


- Project name: Mika-sama
- Project version: version 1
- Stakeholder: Admin, Co-host, Chat channel
- Purpose: Building an AI Vtuber named Mika-sama, to talk and make everyone happy.
- System Architecture: Event-driven Microservices
- System roles:
	+ Mac M1 is the Orchestrator: LLM machine, state, conversation history, memory (FIFO cache + RAG), database, output filter, and all routing decisions. It is the only machine that owns state.
	+ Acer is I/O only: Text-to-Speech, Speech-to-Text, chat listener, and hosting the React pages (Live2D avatar, transcript overlay, admin chatbox). It forwards input to the Mac and renders/plays what the Mac sends back. It makes no orchestration decisions.
	+ Audio output device: the browser page that renders the Live2D model (captured by OBS as a browser source), not the Acer's native audio output.
- System constraint: No subsystem is allowed to assume that the LLM is the source of truth. The personality of the model should let it develop it own (No hardcode in it).


- Code sharing method: GitHub	
- Python environment: Conda + Pip
- Python version: 3.11.9
- Library storing file: requirements.txt
- Configuration file: YAML for personality, python for LLM system configuration
- Secret file: ENV for database
- Log method: Store in server.log file


- Frontend: Dynamic Transcript HTML, Live2D, OBS, React + TypeScript components for 2D model control and transcription control. The browser plays the TTS audio and drives lipsync (see "Audio and lipsync").
- Backend: Ollama Async Streaming Chat. If we use Streaming token, we need to calculate the timing of chunking text for TTS system usage when LLM hits EOF of the response text (flush the remaining buffer as the last sentence).
- Streamming Text System: In this streaming system, we will use State-buffered Sentence Chunking methods to build a text chunking system based on English puncts rule. The output filter runs on whole sentences produced by the chunker, never on single tokens.
- Streaming pipeline order (Mac side):
	+ LLM raw token stream -> Emotion tag parser -> Normalizer -> Sentence Chunker -> Output Filter (per sentence) -> Approved sentence -> sent to Acer over /ws/runtime


- API endpoint (Middleware CORS permission required): 
 + /ws/runtime: The Orchestrator channel (Mac M1 side). The Acer connects here to forward user input and receive approved sentences, emotion events and control events.
 + /ws/chat: Bridge between the React pages and the Acer (Acer side). Carries admin chat messages up to the Acer, and carries emotion, transcript text and TTS audio chunks down to the browser.
 + /synthesize: REMOVED. The Acer runs TTS itself on each approved sentence it receives over /ws/runtime and pushes the audio to the browser over /ws/chat.


- API type used: Hybrid model (Stateless + external state) and Websocket. The external state lives only on the Mac.
- Connectivity: WebSocket for the runtime communication, HTTP for management/API operations. Use CORS middleware in FastAPI to allow client to connect to the server. Add @asynccontextmanager to manage the context when the server start up.
- Database: Postgres (persistent data)
- Data connect/query method: Using psycopg_pool (AsyncConnectionPool) from psycopg3 Python library (Require pip install psycopg and psycopg_pool)
- Embedding Vector (RAG + RAR): Use pgvector Python Library + Retrieval-Augmented Reasoning Layer
	+ Embedding model: nomic-embed-text (768 dimensions). It runs on the Mac's CPU inside the server process, not through Ollama, so it never unloads llama3.1:8b from the 8 GB Mac.
- Message caching method: FIFO (First-In, First-Out)
- Request message and receive message method/format: JSON
- LLM system should be reused every time user requests to the server.
- Run script: run_client.ps1 for Client API, run_server.bash for Server API (Maybe don't need)


- Intent schema: casual_conversation, filter_incident, error_recovery
- Emotion schema: happy, sad, confused, angry, neutral
- Server/System State schema: shutting_down, client_status, service_status, personality (Use Field(dict)), current_emotion
- Request payload (Acer -> Mac): user_id, message
	+ The client sends nothing else. The server builds history (from the FIFO cache), rag_context (from pgvector) and the personality prompt itself.
	+ Admin messages (chatbox and voice) use the fixed user_id "admin".
- Response payload: intent, emotion, reply, original_reply, action
	+ reply = what was actually spoken (after filtering), original_reply = raw LLM output, action = FilterAction
- Database schema: 
 + chat_logs table: id, session_id, user_id, user_message, rag_context_used, mika_intent, mika_emotion, mika_reply, original_reply, filter_action, filter_reason, created_at
 + users table: user_id, username, platform, interaction_count, created_at, last_seen
 + memory_embeddings table: id, chat_log_id (FK -> chat_logs.id), content, embedding (pgvector), created_at
 + personality_traits table: id, trait, source_chat_log_id (FK -> chat_logs.id), active, created_at


- Main features: Streaming Token Process, Intent Detector, Emotion Manager, Personality Prompt Engine, Response Output Protocol.
- LLM API used: Ollama
- LLM model: Llama3.1:8b
- Intent Detector Method: set by the system, not the LLM. filter_incident if any sentence of the reply was not ALLOW, error_recovery if the turn hit an error or timeout, otherwise casual_conversation.
- Text Inference Method: Self-supervised 
- LLM configuration: temperature=0.7, num_predict=150 (spoken replies)
- Startup method: use startup/lifespan function to load the model with Personality Prompt Engine when starting up the server.
- System configuration (Python): SERVER_WS_URL, VOICE_MODEL, REF_VOICE_PATH, REF_TEXT
- ENV configuration: DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
	+ TEST_DB_NAME (optional): a separate database the tests may wipe. Never the real database.
- YAML configuration: name, role, core_identity, guidelines


- Emotion Manager (emotion during streaming):
	+ The system prompt tells the LLM to begin every reply with exactly one tag from the emotion schema, e.g. `[happy]`.
	+ The server buffers the start of the stream until the tag is closed, parses it, strips it from the text, and sends an emotion event to the Acer before the first sentence.
	+ The tag is validated against the emotion schema. A missing or invalid tag falls back to `neutral` (the LLM is not the source of truth).
	+ The Acer forwards the emotion event to the browser, which switches the Live2D expression.
- Live2D expressions:
	+ Create one expression file (.exp3.json) per emotion in the emotion schema (happy, sad, confused, angry, neutral) and register them under `FileReferences.Expressions` in the model3.json.
	+ Expressions must not change ParamMouthOpenY, because lipsync owns that parameter.


- STT Engine: Detect user voice activity through VAD + RMS.
	+ Half-duplex: STT is muted while Mika speaks, so she never transcribes her own voice.
	+ Because audio plays in the browser, the browser reports playback back to the Acer over /ws/chat (playback started / playback finished). The Acer mutes STT from the start of a reply until the browser reports that the reply's last audio chunk has finished.
	+ Interrupting Mika while she speaks is out of scope for v1.
	+ Transcription: faster-whisper on CPU (int8). Voice activity: silero-vad, with RMS as a noise gate.
- TTS Engine: Use GenieTTS for CPU performance.
- Audio and lipsync:
	+ The Acer synthesizes each approved sentence with GenieTTS and sends the audio chunk, together with its sentence text and a sequence number, to the browser over /ws/chat.
	+ Audio chunks travel as WAV, base64-encoded inside JSON messages (v1).
	+ The browser queues the chunks in order, plays them with the Web Audio API, and drives ParamMouthOpenY from the playing audio's amplitude.
	+ The transcript overlay shows each sentence when its audio starts playing.
	+ In OBS, the avatar page is a browser source with "Control audio via OBS" enabled, so the stream captures the audio.
- Personality Prompt Engine: The root personality file (YAML) load into the LLM system when startup, and it can be used as a basic personality to be appended by any classification as it needed.
	+ Two layers: the YAML core_identity is fixed. Traits Mika develops over time are stored in the personality_traits table and appended to the prompt after the YAML. This is how "let it develop its own personality" is met without changing the core.
	+ v1 only reads personality_traits; the admin can insert rows by hand. Writing new traits automatically comes later.


- Output Filter Protocol (FilterAction):
	+ ALLOW: Send the sentence to TTS and put it into memory.
	+ REPLACE: Send "Filtered" + toast response to TTS instead of the sentence, then put the response into memory.
	+ BLOCK: Discard the pending unsafe segment, generate a safe replacement, and send the replacement to TTS.
	+ Memory stores original_reply (the unfiltered LLM output) for every response, together with reply and action.
	+ The prompt context (history) is built from both reply and original_reply.
- Filter stages:
	+ Hard rules (prohibited words file) -> BLOCK.
	+ AI Classifier -> REPLACE. It uses llama3.1:8b and judges each sentence with context: the user's message, recent history and the reply so far. The extra latency is accepted.
	+ BLOCK replacement: a second llama3.1:8b call generates the safe replacement sentence. The replacement is checked by the filter again before it is spoken.
	+ If the AI Classifier times out or returns invalid output, the sentence is treated as unsafe (REPLACE).
	+ After a BLOCK, the replacement is spoken and the rest of the reply keeps going through the filter.


- Conversation data collectting method: Secondary data + AI Response
- Finetune method: Unsloth (Colab GPU method) (Later after collected 1000 conversations data)
	+ The fine-tuning dataset is built from reply only, never original_reply.
- Other features: Play game, singing, monitor vision inference.


- Acknowledge issues:
 + Deadlock occurred when trying to use asyncio.Queue to manage works.
 + Websockets disconnection swallowed Cancelled Exception, making server unable to shutdown probably.
 + Transcription and lipsync function cannot be fired up to use on OBS/Chrome. (Addressed by design: audio now plays in the browser, which drives lipsync and transcript timing.)
 + Hard to implement TTS and lipsync for streaming token LLM response because of confliction in architecture. (Addressed by design: sentence-level audio chunks with sequence numbers, see "Audio and lipsync".)


- Strategy to handle deadlock work queue: Replaced .get() or .join() calls with non-blocking async loop, add strict timeout for queue accquisition and token generation task, and configure maximum queue lengths with rejection policies.


### Decision log

| Date | Decision | Supersedes |
|------|----------|------------|
| 2026-09-26 | Mac M1 is the only orchestrator; Acer is I/O only. | "Orchestrator: Acer (Client)" in `STT System with VAD.md` |
| 2026-09-26 | Create Live2D expressions (.exp3.json) for each emotion in the emotion schema. | "trigger an expression/hotkey" in `Build a React Page.md` (the model has no expressions or hotkeys yet) |
| 2026-09-26 | BLOCK = discard the pending unsafe segment, generate a safe replacement, speak the replacement. | The other two BLOCK definitions in `Ouput Filter Protocol.md` (stop TTS at the word; speak a toast) |
| 2026-09-26 | Memory stores original_reply. | — |
| 2026-09-26 | Pipeline order: Normalizer -> Sentence Chunker -> Filter (per sentence) -> TTS. | "Increment Filter -> Approved Text Stream -> Text Chunker" in `Ouput Filter Protocol.md` |
| 2026-09-26 | Emotion is sent as a leading `[emotion]` tag, validated, fallback `neutral`. | — |
| 2026-09-26 | TTS audio chunks are played in the browser, which drives lipsync. | Acer native audio output |
| 2026-09-26 | Request payload is user_id + message only; the server builds history and rag_context. | "Request payload: user_id, message, history, rag_context" |
| 2026-09-26 | /synthesize endpoint removed. | /synthesize endpoint |
| 2026-09-27 | BLOCK replacement is generated by a second llama3.1:8b call. | — |
| 2026-09-27 | AI Classifier uses llama3.1:8b with conversation context; latency accepted. | — |
| 2026-09-27 | Prompt context is built from both reply and original_reply. | — |
| 2026-09-27 | DB schema extended: chat_logs (+session_id, original_reply, filter_action, filter_reason), users (+username, platform), new memory_embeddings and personality_traits tables. | Old chat_logs / users schema |
| 2026-09-27 | Personality has two layers: fixed YAML core + learned traits from the DB. | — |
| 2026-09-27 | STT is half-duplex, driven by browser playback events. Interruption is deferred. | — |
| 2026-09-27 | Intent is set by the system (filter_incident / error_recovery / casual_conversation), not by the LLM. | "Intent Detector Method: Self-supervised" |
| 2026-09-27 | num_predict=150 for spoken replies. | num_predict=400 |
| 2026-09-27 | Embedding model: nomic-embed-text, vector(768). | — |
| 2026-09-27 | AI Classifier timeout or invalid output = unsafe (REPLACE). After a BLOCK, the reply continues. | — |
| 2026-09-27 | v1 only reads personality_traits; automatic trait writing comes later. | — |
| 2026-09-27 | Fine-tuning data is built from reply only. | — |
| 2026-09-27 | STT: faster-whisper (CPU, int8) + silero-vad + RMS gate. | — |
| 2026-09-27 | Audio chunks are base64 WAV inside JSON (v1). Admin uses user_id "admin". | — |
| 2026-09-27 | Embeddings run on the Mac's CPU inside the server process, not through Ollama. | — |
| 2026-09-30 | Database tests use a separate database named by TEST_DB_NAME. On the Acer it runs in WSL Ubuntu (PostgreSQL 16 + pgvector, port 5433). | — |
| 2026-10-01 | Starting personality (mika/server/data/personality.yaml): the earlier v21 personality (character, guidelines) merged with v54 (warmth, interests, "Ehehe~" catchphrase). The reply-format rules (emotion tag, short spoken sentences) live in code, not in the YAML. | — |
