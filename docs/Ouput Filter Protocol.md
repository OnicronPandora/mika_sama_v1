### Output Filter Protocol:

- Base Architecture: LLM -> Output Filter System -> FilterAction 
- Stream LLM Filter workflow: LLM -> Raw Stream -> Normalizer -> Increment Filter (BLOCK, REPLACE, ALLOW) -> Approved Text Stream -> Text Chunker -> TTS Queue -> Audio
- Output Filter System features: Normalizer, Hard Rules, AI Classifier, Policy Engine

- The Filter system use 2 types: 
 + The hardcode filter system using file to prohibit the exact inappropriate word in the the response, then make it unable to display or trigger TTS on inappropriate word in the response.
 + The AI Filter: Judge the response if the response content is inappropriate, then fallback to use a toast response to against/replace that response.

- FilterAction (Enum): ALLOW, REPLACE, BLOCK
 + If ALLOW (for normal response): Trigger TTS, then put the response into memory (speak approved text for streaming token)
 + If REPLACE (for response content): Trigger TTS with "Filtered + {toast response}, then put the response into the memory (speak replacement text for streaming token)
 + If BLOCK (for response word): Trigger TTS until it touch the prohibited word (Stop TTS process), but still put it into the memory. (speak safe fallback/toast for streaming token)

- Advanced BLOCK behavior: LLM -> Filter -> detect violation -> discard pending unsafe segment -> generate safe replacement -> TTS replacement

- FilterResult schema: action, filter_response, reason