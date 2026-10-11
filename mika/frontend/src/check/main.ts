// Avatar check (check.html): shows each expression, and makes Mika talk with lipsync while it is active.
// Nothing connects to the Acer client; this page only exercises the model.
import { startLipsync } from '../audio/lipsync'
import { createAvatar, type Avatar } from '../live2d/avatar'
import { EMOTIONS } from '../live2d/emotions'
import type { Emotion } from '../types/events'

/** The face, as fractions of the model's height. */
const FACE = { top: 0.12, bottom: 0.31 }

const status = document.querySelector<HTMLDivElement>('#status')!
const show = (text: string): void => {
  status.textContent = text
}

/** About 3 s of buzzing syllables with pauses: something speech-like for the lipsync, without a file. */
function testSound(context: AudioContext): AudioBuffer {
  const rate = context.sampleRate
  const buffer = context.createBuffer(1, Math.round(rate * 3.2), rate)
  const data = buffer.getChannelData(0)
  const syllables = [
    [0.1, 0.32], [0.38, 0.55], [0.6, 0.9], [1.3, 1.45], [1.5, 1.75], [1.82, 2.1], [2.5, 2.7], [2.76, 3.05],
  ]
  for (const [start, end] of syllables) {
    for (let i = Math.round(start * rate); i < Math.round(end * rate); i++) {
      const t = i / rate
      const envelope = Math.sin((Math.PI * (t - start)) / (end - start)) // rises and falls within the syllable
      const voice = Math.sin(2 * Math.PI * 220 * t) + 0.5 * Math.sin(2 * Math.PI * 440 * t) + 0.25 * Math.sin(2 * Math.PI * 660 * t)
      data[i] = 0.12 * envelope * voice
    }
  }
  return buffer
}

function setupEmotions(avatar: Avatar): void {
  const container = document.querySelector<HTMLDivElement>('#emotions')!
  const buttons = new Map<Emotion, HTMLButtonElement>()
  const select = (emotion: Emotion): void => {
    avatar.setEmotion(emotion)
    for (const [name, button] of buttons) button.setAttribute('aria-pressed', String(name === emotion))
  }
  for (const emotion of EMOTIONS) {
    const button = document.createElement('button')
    button.textContent = emotion
    button.addEventListener('click', () => select(emotion))
    buttons.set(emotion, button)
    container.append(button)
  }
  select('neutral')
}

function setupLipsync(avatar: Avatar): void {
  let context: AudioContext | null = null
  let analyser: AnalyserNode
  let playing: AudioBufferSourceNode | null = null
  let stopLipsync: (() => void) | null = null

  const audio = async (): Promise<AudioContext> => {
    if (!context) {
      context = new AudioContext() // created on a click: browsers only allow audio after a user gesture
      analyser = context.createAnalyser()
      analyser.fftSize = 1024
      analyser.connect(context.destination)
    }
    await context.resume()
    return context
  }

  const play = (buffer: AudioBuffer, name: string): void => {
    playing?.stop()
    const source = context!.createBufferSource()
    source.buffer = buffer
    source.connect(analyser)
    stopLipsync ??= startLipsync(analyser, avatar.setMouth)
    source.onended = () => {
      if (playing !== source) return
      playing = null
      stopLipsync?.()
      stopLipsync = null
      show(`Played ${name}`)
    }
    playing = source
    source.start()
    show(`Playing ${name} (${buffer.duration.toFixed(1)} s)`)
  }

  document.querySelector('#talk')!.addEventListener('click', async () => {
    play(testSound(await audio()), 'the test sound')
  })
  document.querySelector<HTMLInputElement>('#wav')!.addEventListener('change', async (event) => {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = '' // the same file can be chosen again
    if (!file) return
    try {
      const context = await audio()
      play(await context.decodeAudioData(await file.arrayBuffer()), file.name)
    } catch (err) {
      show(`Couldn't play ${file.name}: ${err instanceof Error ? err.message : String(err)}`)
    }
  })
}

function setupView(avatar: Avatar): void {
  const body = document.querySelector<HTMLButtonElement>('#view-body')!
  const face = document.querySelector<HTMLButtonElement>('#view-face')!
  const select = (faceView: boolean): void => {
    if (faceView) avatar.frame(FACE.top, FACE.bottom)
    else avatar.frame(0, 1)
    body.setAttribute('aria-pressed', String(!faceView))
    face.setAttribute('aria-pressed', String(faceView))
  }
  body.addEventListener('click', () => select(false))
  face.addEventListener('click', () => select(true))
}

async function main(): Promise<void> {
  const avatar = await createAvatar(document.querySelector<HTMLCanvasElement>('#stage')!)
  Object.assign(window, { avatar }) // for the browser console
  setupEmotions(avatar)
  setupLipsync(avatar)
  setupView(avatar)
  show('Ready')
}

main().catch((err: unknown) => {
  show(`Error: ${err instanceof Error ? err.message : String(err)}`)
  console.error(err)
})
