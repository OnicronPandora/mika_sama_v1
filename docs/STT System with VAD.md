### STT System with VAD:

- Context: This system will handle Speak-to-Text, also tracking voice activities of the admin.

- Method: Use asyncio.Queue to enqueue the voice to concatenate string.

- Problem found when first implementation: System has been deadlocked after the shutdown (Cause by Queue.get() method)

- Orchestrator: Acer (Client)

- Workflow should be: Voice -> VAD -> STT transcribe the voice -> Text -> Send text to Server -> Server send response -> TTS -> Log response into Database -> STT


