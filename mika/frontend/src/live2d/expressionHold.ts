// Mika keeps a reply's expression until the next reply. If none comes, she goes back to neutral once she has been
// quiet for EXPRESSION_HOLD_SECONDS (Pandora's choice, 2026-10-11: 5 minutes).
import type { Emotion } from '../types/events'

export class ExpressionHold {
  private timer: ReturnType<typeof setTimeout> | undefined
  private current: Emotion = 'neutral'

  constructor(
    private readonly setEmotion: (emotion: Emotion) => void,
    private readonly holdSeconds: number,
  ) {}

  /** A reply's emotion: shown now, and kept until the next one or until she has been quiet long enough. */
  show(emotion: Emotion): void {
    this.current = emotion
    this.setEmotion(emotion)
    this.restart()
  }

  /** She has just been talking: the quiet time counts from now. */
  touch(): void {
    this.restart()
  }

  close(): void {
    clearTimeout(this.timer)
  }

  private restart(): void {
    clearTimeout(this.timer)
    if (this.current === 'neutral') return
    this.timer = setTimeout(() => {
      this.current = 'neutral'
      this.setEmotion('neutral')
    }, this.holdSeconds * 1000)
  }
}
