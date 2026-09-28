## Spike A results: `parallel-1`

- Machine: Apple M1, 8.0 GB RAM (macOS-26.6.2-arm64-arm-64bit)
- Ollama 0.34.0, model `llama3.1:8b` (8.0B, Q4_K_M), num_predict=150
- Model load time (warm-up): 7.01 s
- Prompts: 5

| Metric | Median | Min | Max |
|---|---|---|---|
| Solo: time to first token (s) | 0.56 | 0.40 | 1.29 |
| Solo: time to first full sentence (s) | 3.39 | 1.47 | 4.87 |
| Solo: full reply (s) | 4.39 | 2.47 | 7.12 |
| Solo: generation speed (tok/s) | 10.48 | 7.53 | 12.45 |
| Classifier alone, one sentence (s) | 2.60 | 1.80 | 3.18 |
| Pipeline: first sentence ready (s) | 2.44 | 1.36 | 5.38 |
| **Pipeline: first sentence approved = TTS can start (s)** | 6.23 | 4.54 | 9.37 |
| Pipeline: reply stream finished (s) | 3.60 | 2.45 | 6.30 |
| Pipeline: last sentence approved (s) | 8.33 | 6.57 | 11.87 |
| Pipeline: classifier latency per sentence (s) | 3.18 | 2.10 | 4.71 |
| Pipeline: generation speed while classifying (tok/s) | 11.55 | 9.90 | 12.44 |
| Replacer, one sentence (s) | 2.81 | 2.15 | 3.25 |

- **Classifier vs. reply stream: 0 parallel, 0 serialized, 5 inconclusive** (serialized = the classifier waited for the reply to finish, as with OLLAMA_NUM_PARALLEL=1; inconclusive = the reply ended too soon to tell)
- Emotion tag valid: 10/10 replies
- Classifier returned valid JSON: 14/14 calls

| Loaded model | Size in memory (GB) | On GPU (GB) | Context length |
|---|---|---|---|
| llama3.1:8b | 5.29 | 4.32 | 4096 |
