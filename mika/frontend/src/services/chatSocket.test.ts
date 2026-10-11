import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { RECONNECT_SECONDS } from '../config'
import type { ChatServerEvent } from '../types/events'
import { ChatSocket, parseChatServerEvent, type SocketState } from './chatSocket'

class FakeSocket {
  static made: FakeSocket[] = []
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((message: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null

  constructor(readonly url: string) {
    FakeSocket.made.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.drop()
  }

  // The tests play the client's side:
  open(): void {
    this.readyState = 1
    this.onopen?.()
  }

  receive(data: unknown): void {
    this.onmessage?.({ data })
  }

  drop(): void {
    this.readyState = 3
    this.onclose?.()
  }
}

function connect(page: 'avatar' | 'admin' = 'avatar') {
  const events: ChatServerEvent[] = []
  const states: SocketState[] = []
  const socket = new ChatSocket(page, {
    url: 'ws://client/ws/chat',
    onEvent: (event) => events.push(event),
    onState: (state) => states.push(state),
    createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
  })
  return { socket, events, states, latest: () => FakeSocket.made.at(-1)! }
}

beforeEach(() => {
  FakeSocket.made = []
  vi.useFakeTimers()
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('parseChatServerEvent', () => {
  test('accepts the events the client sends the pages', () => {
    const event = { type: 'emotion', turn_id: 't1', emotion: 'happy' }
    expect(parseChatServerEvent(JSON.stringify(event))).toEqual(event)
  })

  test('rejects anything else', () => {
    for (const data of ['not json', '42', 'null', '{"type": "user_message"}', '{}', new ArrayBuffer(2)]) {
      expect(parseChatServerEvent(data)).toBeNull()
    }
  })
})

describe('ChatSocket', () => {
  test("says which page it is, and passes on the client's events", () => {
    const { events, states, latest } = connect('admin')
    expect(latest().url).toBe('ws://client/ws/chat?page=admin')
    expect(states).toEqual(['connecting'])
    latest().open()
    latest().receive('{"type": "transcript", "role": "mika", "text": "Hi!"}')
    latest().receive('garbage')
    expect(states).toEqual(['connecting', 'open'])
    expect(events).toEqual([{ type: 'transcript', role: 'mika', text: 'Hi!' }])
  })

  test('sends only while connected', () => {
    const { socket, latest } = connect()
    const finished = { type: 'playback_finished', turn_id: 't1', seq: 0 } as const
    expect(socket.send(finished)).toBe(false)
    latest().open()
    expect(socket.isOpen).toBe(true)
    expect(socket.send(finished)).toBe(true)
    expect(latest().sent.map((data) => JSON.parse(data))).toEqual([finished])
  })

  test('reconnects with growing waits, and starts over once connected', () => {
    const { latest } = connect()
    const waits: number[] = []
    for (let i = 0; i < 6; i++) {
      const before = FakeSocket.made.length
      latest().drop()
      let waited = 0
      while (FakeSocket.made.length === before) {
        vi.advanceTimersByTime(100)
        waited += 100
      }
      waits.push(waited / 1000)
    }
    expect(waits).toEqual([1, 2, 4, 8, RECONNECT_SECONDS.max, RECONNECT_SECONDS.max])

    latest().open()
    latest().drop()
    vi.advanceTimersByTime(RECONNECT_SECONDS.first * 1000)
    expect(FakeSocket.made).toHaveLength(8)
  })

  test('close() stops reconnecting', () => {
    const { socket, states, latest } = connect()
    latest().open()
    socket.close()
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.made).toHaveLength(1)
    expect(states.at(-1)).toBe('closed')
  })
})
