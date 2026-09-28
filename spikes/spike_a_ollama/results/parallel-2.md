## Spike A results: `parallel-2`

- Machine: Apple M1, 8.0 GB RAM (macOS-26.6.2-arm64-arm-64bit)
- Ollama 0.34.0, model `llama3.1:8b` (8.0B, Q4_K_M), num_predict=150
- Model load time (warm-up): 6.28 s
- Prompts: 5

| Metric | Median | Min | Max |
|---|---|---|---|
| Solo: time to first token (s) | 0.43 | 0.40 | 1.45 |
| Solo: time to first full sentence (s) | 2.52 | 1.48 | 3.67 |
| Solo: full reply (s) | 3.71 | 3.50 | 4.62 |
| Solo: generation speed (tok/s) | 11.85 | 10.08 | 12.33 |
| Classifier alone, one sentence (s) | 2.78 | 1.94 | 3.45 |
| Pipeline: first sentence ready (s) | 2.57 | 1.28 | 3.81 |
| **Pipeline: first sentence approved = TTS can start (s)** | 5.55 | 4.08 | 8.18 |
| Pipeline: reply stream finished (s) | 3.58 | 1.86 | 5.68 |
| Pipeline: last sentence approved (s) | 5.96 | 4.70 | 12.86 |
| Pipeline: classifier latency per sentence (s) | 2.44 | 1.84 | 4.37 |
| Pipeline: generation speed while classifying (tok/s) | 12.46 | 10.63 | 12.78 |
| Replacer, one sentence (s) | 2.47 | 1.70 | 2.89 |

- **Classifier vs. reply stream: 0 parallel, 0 serialized, 5 inconclusive** (serialized = the classifier waited for the reply to finish, as with OLLAMA_NUM_PARALLEL=1; inconclusive = the reply ended too soon to tell)
- Emotion tag valid: 10/10 replies
- Classifier returned valid JSON: 14/14 calls

| Loaded model | Size in memory (GB) | On GPU (GB) | Context length |
|---|---|---|---|
| llama3.1:8b | 5.29 | 4.32 | 4096 |
