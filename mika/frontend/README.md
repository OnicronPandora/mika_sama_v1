# Mika-sama frontend (Acer)

The browser pages ([implementation plan](../../docs/implementation_plan.md), Phases 8 and 9), served on the Acer by
Vite and connected to the Acer client (`mika/client`) on `ws://127.0.0.1:8001/ws/chat`:
- **`/avatar`**, for OBS or Chrome: Mika's Live2D model, her voice with lipsync, and a subtitle for the sentence she
  is saying;
- **`/admin`**, for Pandora: the chatbox, the conversation, and how the Acer client and the Mac are doing;
- **`/check.html`**: each expression, and lipsync with it, without the client.

Stack, with exact versions: React 19 + TypeScript, and from Spike C, easy-live2d 1.0.0 + PixiJS 8.21 (WebGL 2) +
Cubism Core 6.0.1 from the Cubism SDK for Web R5, served by Vite 8.

## Setup (once, on the Acer)

```bash
cd mika/frontend
npm install
```

Two files that can't be in git come from Live2D, under their own licenses:
- **The model:** Live2D's sample model "初音ミク PRO版" (<https://www.live2d.com/download/sample-data/>); its `runtime`
  folder goes to `others/2D/miku_pro/runtime`.
- **Cubism Core:** download the Cubism SDK for Web R5 from <https://www.live2d.com/en/sdk/download/web/> and copy
  `Core/live2dcubismcore.min.js` to `mika/frontend/public/`. The Core on Live2D's CDN is version 5.1, which
  easy-live2d 1.0.0 rejects.

## Run

```bash
npm run dev
```

It first puts the model together in `public/models/miku` (git-ignored): the runtime files, plus the expressions
from `live2d/expressions`, registered in its `model3.json`. Then Vite serves the pages on port 5173 (always 5173:
the Acer client only accepts pages from it). <http://localhost:5173> links to them.

The pages connect to the Acer client (`python -m app` in `mika/client`) and keep reconnecting, so the order you
start things in doesn't matter. Mika answers once the client is connected to the Mac's server.

## The avatar page

<http://localhost:5173/avatar>, in OBS as a browser source (Phase 10) or in Chrome. Open it in one place only: every
avatar page plays Mika's voice.
- **Expression:** each reply's emotion, from the moment the Mac sends it. She keeps it until the next reply, and goes
  back to neutral after 5 minutes without one (`EXPRESSION_HOLD_SECONDS` in `src/config.ts`).
- **Voice and lipsync:** the sentences play one after another, in order; her mouth follows the audio's volume. The
  page tells the client when each sentence starts and finishes playing: after the reply's last one, the client
  turns the microphone back on.
- **Subtitle:** each sentence appears when its audio starts, and fades 4 s after the reply's last one.
- **Chrome** only plays audio after a click on the page, so it shows "Click to turn on Mika's voice" until it gets
  one. A reply that arrives before that click shows its subtitles without sound (playing it later could happen
  after the microphone is back on). OBS doesn't ask for a click.
- **Framing:** the upper body, so that her expressions read on stream. `/avatar?top=0&bottom=1` shows the whole
  body; `top` and `bottom` are fractions of the model's height. The page is transparent.

In the browser console, `avatar` is the model (try `avatar.setEmotion('sad')`) and `audio` the Web Audio output.

## The admin page

<http://localhost:5173/admin>. Enter sends a message (Shift+Enter starts a new line). Your message shows in the
conversation once it has reached the Mac; Mika's reply grows sentence by sentence as the Mac approves them. A
notice says when something went wrong, for example "The Mac isn't reachable, so Mika didn't get that message."

The bar on top comes from the client's `/health`: the client itself, the Mac, Mika's voice, listening, the
microphone (muted while Mika answers) and the avatar page.

## Check the avatar

<http://localhost:5173/check.html> shows Mika as the avatar page does, with her idle motions:
- **Expression:** one button per emotion; each fades in over half a second.
- **Lipsync:** "Talk" plays a buzzing test sound and her mouth follows it; "Play a WAV file…" does the same with
  any WAV, such as a GenieTTS sentence. The mouth should move with every expression.
- **View:** the whole body, or her face.

Nothing connects to the client; the page only exercises the model.

## Expressions

One file per emotion in `live2d/expressions`, plain JSON:

| Emotion | Eyes | Brows | Mouth | Cheeks |
|---------|------|-------|-------|--------|
| neutral | open | | the model's smile | |
| happy | smiling, half closed, or closed (^^) when the motion closes them | | smile | blush |
| sad | droopy (0.75) | lowered, inner ends up | frown | |
| angry | narrowed (0.8) | lowered, inner ends down | frown | |
| confused | open, glancing up and aside | one lowered and worried | flat | |

To change one, edit its file, run `npm run model`, and reload the page. The rules, which `npm test` checks:
- never `ParamMouthOpenY`: lipsync owns the mouth opening (spec);
- `ParamMouthForm` and `ParamEyeLSmile`/`RSmile` use the `Overwrite` blend, because the idle motions animate them;
- `ParamEyeLOpen`/`ROpen` use `Overwrite` or `Multiply`;
- values stay in the model's ranges, and the file stays plain ASCII without exponents (Cubism's JSON parser
  supports neither).

Two things about this model shape the expressions:
- **The brows hide under the bangs** unless they are lowered, so only the lowered brows of sad, angry and confused
  show.
- **The idle motions keep her eyes closed in a smile (^^) about 63% of the time**, and never blink. Every
  expression but happy holds the eyes open, and `src/live2d/blink.ts` makes her blink every 2-6 s on top of the
  motion and the expression. `scripts/copy-model.mjs` removes the model's `EyeBlink` group: easy-live2d runs
  Cubism's own eye blink only in the frames between two idle motions, where it reopened the eyes of a sad or angry
  face for one frame.

## Tests

```bash
npm test
npm run build
```

`npm test` checks the expression files, the blink timing, the lipsync math, the order in which the avatar page plays
a reply and reports it, the 5-minute expression hold, the reconnecting socket and the admin page's log and status
bar. `npm run build` type-checks and bundles the pages into `dist/` (git-ignored).
