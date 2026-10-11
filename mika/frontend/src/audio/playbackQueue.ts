// The avatar page's player. The Acer sends each turn's emotion, audio chunks and turn_end in that order, one turn
// after another; the queue goes through them in the same order. A chunk is decoded as soon as it arrives and
// played after the one before it, and the page reports playback_started and playback_finished for each: after
// the turn's last one, the Acer reopens the microphone (half-duplex).
import type {
  AudioChunk,
  ChatTurnEnd,
  Emotion,
  EmotionUpdate,
  PlaybackFinished,
  PlaybackStarted,
} from '../types/events'
import type { AudioOutput, Clip } from './output'

export type AvatarEvent = EmotionUpdate | AudioChunk | ChatTurnEnd

export interface PlaybackHandlers {
  /** A turn's emotion, once the turns before it have finished playing. */
  emotion(emotion: Emotion): void
  /** A sentence starts playing: the subtitle shows it (spec). */
  sentence(text: string): void
  /** The turn has nothing more to play. */
  turnOver(): void
  /** For the Acer: playback_started and playback_finished. */
  report(event: PlaybackStarted | PlaybackFinished): void
}

type Step =
  | { kind: 'emotion'; emotion: Emotion }
  | { kind: 'audio'; chunk: AudioChunk; clip: Promise<Clip | null> }
  | { kind: 'end' }

/** The bytes of a base64 string (audio_chunk.audio_b64). */
export function decodeBase64(text: string): ArrayBuffer {
  return Uint8Array.from(atob(text), (char) => char.charCodeAt(0)).buffer
}

export class PlaybackQueue<C extends Clip = Clip> {
  private readonly steps: Step[] = []
  private running = false
  private closed = false

  constructor(
    private readonly output: AudioOutput<C>,
    private readonly handlers: PlaybackHandlers,
  ) {}

  push(event: AvatarEvent): void {
    if (this.closed) return
    if (event.type === 'emotion') this.steps.push({ kind: 'emotion', emotion: event.emotion })
    else if (event.type === 'audio_chunk') this.steps.push({ kind: 'audio', chunk: event, clip: this.decode(event) })
    else this.steps.push({ kind: 'end' })
    if (!this.running) void this.run()
  }

  /** Stops after what is playing now; the rest is dropped. */
  close(): void {
    this.closed = true
    this.steps.length = 0
  }

  private async decode(chunk: AudioChunk): Promise<C | null> {
    try {
      return await this.output.decode(decodeBase64(chunk.audio_b64))
    } catch (err) {
      console.error(`Couldn't decode sentence ${chunk.seq} of turn ${chunk.turn_id}:`, err)
      return null
    }
  }

  private async run(): Promise<void> {
    this.running = true
    try {
      for (let step = this.steps.shift(); step && !this.closed; step = this.steps.shift()) {
        if (step.kind === 'emotion') this.handlers.emotion(step.emotion)
        else if (step.kind === 'end') this.handlers.turnOver()
        else await this.play(step.chunk, await step.clip)
      }
    } finally {
      this.running = false
    }
  }

  private async play(chunk: AudioChunk, clip: Clip | null): Promise<void> {
    const { turn_id, seq } = chunk
    this.handlers.report({ type: 'playback_started', turn_id, seq })
    this.handlers.sentence(chunk.text)
    // Without audio (before the click normal Chrome needs, or a chunk that didn't decode) the sentence counts as
    // played at once: playing it later could happen after the Acer has reopened the microphone.
    if (clip && this.output.unlocked) {
      try {
        await this.output.play(clip as C)
      } catch (err) {
        console.error(`Couldn't play sentence ${seq} of turn ${turn_id}:`, err)
      }
    }
    this.handlers.report({ type: 'playback_finished', turn_id, seq })
  }
}
