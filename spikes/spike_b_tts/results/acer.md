## Spike B results: `acer`

- Machine: Intel64 Family 6 Model 154 Stepping 3, GenuineIntel (12 logical CPUs), Windows-10-10.0.26200-SP0
- Python 3.11.9, onnxruntime 1.22.1, providers: AzureExecutionProvider, CPUExecutionProvider
- Load model + reference audio: 10.78 s; first synthesis (warm-up): 2.61 s
- **Median real-time factor: 0.89** (max 1.23; below 1.0 keeps up)

| # | Words | Audio (s) | Synthesis (s) | RTF | Sentence |
|---|---|---|---|---|---|
| 1 | 2 | 1.24 | 1.53 | 1.232 | Hi everyone! |
| 2 | 5 | 1.56 | 1.62 | 1.04 | Welcome back to the stream. |
| 3 | 13 | 3.56 | 3.2 | 0.897 | Oh no, did your cat really knock the coffee off the desk again? |
| 4 | 17 | 5.36 | 4.77 | 0.89 | The sky looks blue because tiny particles in the air scatter blue light more than red light. |
| 5 | 12 | 3.6 | 3.08 | 0.854 | Hmm, I'm a little confused, can you say that one more time? |
| 6 | 18 | 4.4 | 3.72 | 0.846 | People who are mean in chat make me sad, but I know most of you are really kind. |
| 7 | 13 | 3.48 | 3.1 | 0.891 | Okay, let's play one more round and then we'll take a short break. |
| 8 | 21 | 5.12 | 4.68 | 0.914 | Thank you so much for watching today, I had a lot of fun with all of you, see you next time! |
