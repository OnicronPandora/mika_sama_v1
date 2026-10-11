// Mika's voice plays in the browser (spec: OBS captures the avatar page's audio). One AudioContext; every clip goes
// through an AnalyserNode, which lipsync reads.

export interface Clip {
  readonly duration: number
}

/** What the playback queue needs from the audio side (tests use a fake). */
export interface AudioOutput<C extends Clip = Clip> {
  /** False until the browser allows audio: normal Chrome needs a click on the page first, OBS doesn't. */
  readonly unlocked: boolean
  /** Decodes a whole WAV file. */
  decode(wav: ArrayBuffer): Promise<C>
  /** Plays the clip; resolves when it has ended. */
  play(clip: C): Promise<void>
}

/** A clip that hasn't ended this long after its length is given up on (a suspended context never ends it). */
const GRACE_SECONDS = 2

export class WebAudioOutput implements AudioOutput<AudioBuffer> {
  readonly context = new AudioContext()
  readonly analyser: AnalyserNode

  constructor() {
    this.analyser = this.context.createAnalyser()
    this.analyser.fftSize = 1024
    this.analyser.connect(this.context.destination)
  }

  get unlocked(): boolean {
    return this.context.state === 'running'
  }

  /** Call it from a click: browsers allow audio after a user gesture. */
  unlock(): Promise<void> {
    return this.context.resume()
  }

  /** `listener` runs whenever `unlocked` may have changed. */
  onChange(listener: () => void): void {
    this.context.addEventListener('statechange', listener)
  }

  decode(wav: ArrayBuffer): Promise<AudioBuffer> {
    return this.context.decodeAudioData(wav)
  }

  play(clip: AudioBuffer): Promise<void> {
    return new Promise((resolve) => {
      const source = this.context.createBufferSource()
      source.buffer = clip
      source.connect(this.analyser)
      const timer = setTimeout(() => {
        source.onended = null
        try {
          source.stop()
        } catch {
          // the context is already closed
        }
        done()
      }, (clip.duration + GRACE_SECONDS) * 1000)
      const done = (): void => {
        clearTimeout(timer)
        source.disconnect()
        resolve()
      }
      source.onended = done
      source.start()
    })
  }

  close(): void {
    void this.context.close()
  }
}
