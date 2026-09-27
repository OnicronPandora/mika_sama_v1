// Spike C: render miku_sample_t04 with easy-live2d + PixiJS 8, and drive ParamMouthOpenY from code,
// including from the volume of real TTS audio played through Web Audio (the planned lipsync path).
import { Application } from 'pixi.js'
import { Config, Live2DSprite, Priority } from 'easy-live2d'

declare const Live2DCubismCore: { Version: { csmGetVersion(): number } }

const MODEL_URL = '/models/miku/miku_sample_t04.model3.json'
const SAMPLE_URL = '/samples/acer_08.wav'
const MOUTH = 'ParamMouthOpenY'
const LIPSYNC_GAIN = 6 // speech RMS is ~0.05–0.15; this maps it to roughly 0.3–0.9

const statusEl = document.querySelector<HTMLDivElement>('#status')!
const state = { ready: false, mouth: 0, coreVersion: '', errors: [] as string[], info: {} as Record<string, unknown> }
;(window as unknown as { __spike: typeof state }).__spike = state

function render(): void {
  statusEl.textContent = [
    `Cubism Core: ${state.coreVersion}`,
    `Model ready: ${state.ready}`,
    `Mouth value set: ${state.mouth.toFixed(2)}`,
    ...Object.entries(state.info).map(([k, v]) => `${k}: ${JSON.stringify(v)}`),
    ...state.errors.map((e) => `ERROR: ${e}`),
  ].join('\n')
}

function coreVersion(): string {
  const v = Live2DCubismCore.Version.csmGetVersion()
  return `${(v >>> 24) & 0xff}.${(v >>> 16) & 0xff}.${v & 0xffff}`
}

async function main(): Promise<void> {
  state.coreVersion = coreVersion()
  render()

  Config.MotionGroupIdle = 'Idle'
  const canvas = document.querySelector<HTMLCanvasElement>('#stage')!
  const app = new Application()
  await app.init({
    canvas,
    backgroundAlpha: 0, // transparent, as the OBS browser source needs
    resizeTo: window,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
  })

  const sprite = new Live2DSprite({ modelPath: MODEL_URL })
  sprite.width = canvas.clientWidth
  sprite.height = canvas.clientHeight
  app.stage.addChild(sprite)
  await sprite.ready

  state.ready = true
  state.info = {
    renderer: app.renderer.name,
    motions: sprite.getMotions().map((m) => `${m.group}[${m.no}]`),
    expressions: sprite.getExpressions().map((e) => e.name),
    mouthRange: sprite.getParameterValueRangeById(MOUTH),
  }
  render()

  const setMouth = (value: number): void => {
    state.mouth = value
    sprite.setParameterValueById(MOUTH, value)
    render()
  }

  document.querySelector('#mouth-open')!.addEventListener('click', () => setMouth(1))
  document.querySelector('#mouth-close')!.addEventListener('click', () => setMouth(0))

  document.querySelector('#mouth-sine')!.addEventListener('click', () => {
    const start = performance.now()
    const tick = (now: number): void => {
      const t = (now - start) / 1000
      if (t > 3) return setMouth(0)
      setMouth((Math.sin(t * Math.PI * 4) + 1) / 2)
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })

  document.querySelector('#motion-tap')!.addEventListener('click', () => {
    void sprite.startMotion({ group: 'Tap', no: 0, priority: Priority.Force })
  })

  const audioCtx = new AudioContext()
  document.querySelector('#play-sample')!.addEventListener('click', async () => {
    await audioCtx.resume() // browsers only allow audio after a user gesture
    const buffer = await audioCtx.decodeAudioData(await (await fetch(SAMPLE_URL)).arrayBuffer())
    const source = audioCtx.createBufferSource()
    source.buffer = buffer
    const analyser = audioCtx.createAnalyser()
    analyser.fftSize = 1024
    source.connect(analyser)
    analyser.connect(audioCtx.destination)

    const samples = new Float32Array(analyser.fftSize)
    let smoothed = 0
    let frame = 0
    let peak = 0
    const tick = (): void => {
      analyser.getFloatTimeDomainData(samples)
      let sum = 0
      for (const s of samples) sum += s * s
      const target = Math.min(1, Math.sqrt(sum / samples.length) * LIPSYNC_GAIN)
      smoothed += (target - smoothed) * 0.5
      peak = Math.max(peak, smoothed)
      setMouth(smoothed)
      frame = requestAnimationFrame(tick)
    }
    source.onended = () => {
      cancelAnimationFrame(frame)
      setMouth(0)
      state.info = { ...state.info, lastSample: { seconds: buffer.duration.toFixed(2), peakMouth: peak.toFixed(2) } }
      render()
    }
    source.start()
    tick()
  })
}

main().catch((err: unknown) => {
  state.errors.push(err instanceof Error ? `${err.message}\n${err.stack}` : String(err))
  render()
})
