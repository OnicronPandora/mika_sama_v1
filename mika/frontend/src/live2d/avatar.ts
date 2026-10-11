// Mika's Live2D model on a transparent canvas: her expression follows each reply's emotion, and lipsync opens
// her mouth. Stack from Spike C: easy-live2d 1.0.0 + PixiJS 8 (WebGL 2) + Cubism Core from the Cubism SDK for
// Web R5, which the page loads with a <script> tag before this module.
import { Application } from 'pixi.js'
import { Config, Live2DSprite } from 'easy-live2d'
import type { Emotion } from '../types/events'
import { blinker } from './blink'
import { EMOTIONS } from './emotions'

/** Put together by scripts/copy-model.mjs. */
export const MODEL_URL = '/models/miku/miku_sample_t04.model3.json'
/** Lipsync's parameter. No expression touches it (spec), so the mouth moves whatever her emotion. */
export const MOUTH_OPEN = 'ParamMouthOpenY'
/** How open each eye is: the original model3.json's EyeBlink group, which copy-model.mjs removes (see blink.ts). */
const EYES_OPEN = ['ParamEyeLOpen', 'ParamEyeROpen']

export interface Avatar {
  readonly app: Application
  readonly sprite: Live2DSprite
  /** Fades into the emotion's expression (live2d/expressions/<emotion>.exp3.json). */
  setEmotion(emotion: Emotion): void
  /** Opens the mouth, from 0 (closed) to 1. The value holds until the next call: close it when audio ends. */
  setMouth(value: number): void
  /** Shows the model from `top` to `bottom` (fractions of its height, 0-1 for the whole body), centered. */
  frame(top: number, bottom: number): void
  destroy(): void
}

/** Loads the model onto `canvas`, which fills the window, with the neutral expression; she starts blinking. */
export async function createAvatar(canvas: HTMLCanvasElement, modelUrl = MODEL_URL): Promise<Avatar> {
  Config.MotionGroupIdle = 'Idle' // the model's three idle motions play one after another, at random
  Config.MouseFollow = false // her head and eyes don't follow the mouse pointer
  const app = new Application()
  await app.init({
    canvas,
    backgroundAlpha: 0, // transparent, as the OBS browser source needs
    resizeTo: window,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
  })
  const sprite = new Live2DSprite({ modelPath: modelUrl })
  app.stage.addChild(sprite)
  try {
    await sprite.ready
    const names = new Set(sprite.getExpressions().map((expression) => expression.name))
    const missing = EMOTIONS.filter((emotion) => !names.has(emotion))
    if (missing.length > 0) {
      throw new Error(`The model has no expression for: ${missing.join(', ')}. Run npm run model.`)
    }
  } catch (err) {
    app.destroy(false, { children: true })
    throw err
  }

  let view = { top: 0, bottom: 1 }
  const layout = (): void => {
    const model = sprite.getModelCanvasSize()
    if (!model) return
    const scale = app.screen.height / ((view.bottom - view.top) * model.height)
    sprite.scale.set(scale)
    sprite.x = (app.screen.width - model.width * scale) / 2
    sprite.y = -view.top * model.height * scale
  }
  app.renderer.on('resize', layout)
  layout()
  sprite.setExpression({ expressionId: 'neutral' })

  // Every frame: an override of 0 with weight w multiplies the eyes' openness by 1 - w. easy-live2d applies
  // overrides last, after the motion and the expression have set the eyes.
  const blink = blinker()
  app.ticker.add(() => {
    const closure = blink(performance.now() / 1000)
    for (const eye of EYES_OPEN) sprite.setParameterValueById(eye, 0, closure)
  })

  return {
    app,
    sprite,
    setEmotion: (emotion) => sprite.setExpression({ expressionId: emotion }),
    setMouth: (value) => sprite.setParameterValueById(MOUTH_OPEN, Math.min(1, Math.max(0, value))),
    frame: (top, bottom) => {
      view = { top, bottom }
      layout()
    },
    destroy: () => app.destroy(false, { children: true }), // keeps the canvas; releases the model
  }
}
