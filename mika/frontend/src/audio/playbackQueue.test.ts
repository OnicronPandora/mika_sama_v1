import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { AudioChunk, ChatTurnEnd, Emotion, EmotionUpdate } from '../types/events'
import type { AudioOutput } from './output'
import { PlaybackQueue, decodeBase64 } from './playbackQueue'

interface FakeClip {
  duration: number
  name: string
}

/** Decodes a "WAV" that is just its name; each play waits for finish() (or fail()). */
class FakeOutput implements AudioOutput<FakeClip> {
  unlocked = true
  played: string[] = []
  private ends: { resolve(): void; reject(error: Error): void }[] = []

  async decode(wav: ArrayBuffer): Promise<FakeClip> {
    const name = new TextDecoder().decode(wav)
    if (name === 'broken') throw new Error('not a WAV file')
    return { duration: 1, name }
  }

  play(clip: FakeClip): Promise<void> {
    this.played.push(clip.name)
    return new Promise((resolve, reject) => this.ends.push({ resolve, reject }))
  }

  finish(): void {
    this.ends.shift()!.resolve()
  }

  fail(): void {
    this.ends.shift()!.reject(new Error('the audio device went away'))
  }
}

const emotion = (turn_id: string, emotion: Emotion): EmotionUpdate => ({ type: 'emotion', turn_id, emotion })
const chunk = (turn_id: string, seq: number, text: string, audio = text): AudioChunk => ({
  type: 'audio_chunk',
  turn_id,
  seq,
  text,
  audio_b64: btoa(audio),
  sample_rate: 32000,
})
const end = (turn_id: string, last_seq: number | null): ChatTurnEnd => ({ type: 'turn_end', turn_id, last_seq })

/** Lets the queue's promises run. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

function setup() {
  const output = new FakeOutput()
  const timeline: string[] = []
  const queue = new PlaybackQueue(output, {
    emotion: (value) => timeline.push(`emotion ${value}`),
    sentence: (text) => timeline.push(`subtitle ${text}`),
    turnOver: () => timeline.push('turn over'),
    report: (event) => timeline.push(`${event.type} ${event.turn_id}#${event.seq}`),
  })
  return { output, timeline, queue }
}

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

test('decodeBase64 gives back the bytes', () => {
  expect(new Uint8Array(decodeBase64(btoa('RIFF\u0000ÿ')))).toEqual(new Uint8Array([82, 73, 70, 70, 0, 255]))
})

describe('PlaybackQueue', () => {
  test('plays a turn in order and reports each sentence', async () => {
    const { output, timeline, queue } = setup()
    for (const event of [emotion('t1', 'happy'), chunk('t1', 0, 'Hello!'), chunk('t1', 1, 'Nice to see you.'), end('t1', 1)]) {
      queue.push(event)
    }
    await settle()
    expect(timeline).toEqual(['emotion happy', 'playback_started t1#0', 'subtitle Hello!'])
    output.finish()
    await settle()
    output.finish()
    await settle()
    expect(output.played).toEqual(['Hello!', 'Nice to see you.'])
    expect(timeline).toEqual([
      'emotion happy',
      'playback_started t1#0',
      'subtitle Hello!',
      'playback_finished t1#0',
      'playback_started t1#1',
      'subtitle Nice to see you.',
      'playback_finished t1#1',
      'turn over',
    ])
  })

  test("a turn's emotion waits until the turn before it has finished playing", async () => {
    const { output, timeline, queue } = setup()
    for (const event of [emotion('t1', 'happy'), chunk('t1', 0, 'One.'), end('t1', 0), emotion('t2', 'sad'), chunk('t2', 0, 'Two.'), end('t2', 0)]) {
      queue.push(event)
    }
    await settle()
    expect(timeline).not.toContain('emotion sad')
    output.finish()
    await settle()
    expect(timeline.slice(-5)).toEqual(['playback_finished t1#0', 'turn over', 'emotion sad', 'playback_started t2#0', 'subtitle Two.'])
  })

  test('a turn without sentences is over at once', async () => {
    const { timeline, queue } = setup()
    queue.push(emotion('t1', 'confused'))
    queue.push(end('t1', null))
    await settle()
    expect(timeline).toEqual(['emotion confused', 'turn over'])
  })

  test('without audio (before the click Chrome needs), sentences count as played at once', async () => {
    const { output, timeline, queue } = setup()
    output.unlocked = false
    for (const event of [emotion('t1', 'happy'), chunk('t1', 0, 'Hello!'), chunk('t1', 1, 'Bye!'), end('t1', 1)]) queue.push(event)
    await settle()
    expect(output.played).toEqual([])
    expect(timeline).toEqual([
      'emotion happy',
      'playback_started t1#0',
      'subtitle Hello!',
      'playback_finished t1#0',
      'playback_started t1#1',
      'subtitle Bye!',
      'playback_finished t1#1',
      'turn over',
    ])
  })

  test("a chunk that doesn't decode or play is still reported, and the next one plays", async () => {
    const { output, timeline, queue } = setup()
    queue.push(chunk('t1', 0, 'Broken.', 'broken'))
    queue.push(chunk('t1', 1, 'Fine.'))
    queue.push(chunk('t1', 2, 'Cut off.'))
    await settle()
    expect(timeline.slice(0, 3)).toEqual(['playback_started t1#0', 'subtitle Broken.', 'playback_finished t1#0'])
    output.finish()
    await settle()
    output.fail()
    await settle()
    expect(output.played).toEqual(['Fine.', 'Cut off.'])
    expect(timeline.at(-1)).toBe('playback_finished t1#2')
  })

  test('close() drops what is still queued', async () => {
    const { output, timeline, queue } = setup()
    queue.push(chunk('t1', 0, 'One.'))
    queue.push(chunk('t1', 1, 'Two.'))
    await settle()
    queue.close()
    queue.push(chunk('t1', 2, 'Three.'))
    output.finish()
    await settle()
    expect(output.played).toEqual(['One.'])
    expect(timeline.at(-1)).toBe('playback_finished t1#0')
  })
})
