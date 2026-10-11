# Mika-sama frontend (Acer)

The browser side ([implementation plan](../../docs/implementation_plan.md)). So far (Phase 8), Mika's Live2D model with
one expression per emotion, the code that drives it (expressions, blinking, lipsync), and a page to check them. The
avatar and admin pages come in Phase 9.

Stack from Spike C, with exact versions: easy-live2d 1.0.0 + PixiJS 8.21 (WebGL 2) + Cubism Core 6.0.1 from the
Cubism SDK for Web R5, served by Vite 8.

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
the Acer client only accepts pages from it).

## Check the avatar

Open <http://localhost:5173/check.html>. It shows Mika as the avatar page will, with her idle motions:
- **Expression:** one button per emotion; each fades in over half a second.
- **Lipsync:** "Talk" plays a buzzing test sound and her mouth follows it; "Play a WAV file…" does the same with
  any WAV, such as a GenieTTS sentence. The mouth should move with every expression.
- **View:** the whole body, or her face.

Nothing connects to the client; the page only exercises the model. In the browser console, `avatar` is the object
the page drives.

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

`npm test` checks the expression files, the blink timing and the lipsync math. `npm run build` type-checks and
bundles the pages into `dist/` (git-ignored).
