// The admin page's logic: its conversation log and its status bar.
import { describe, expect, test } from 'vitest'
import type { ClientHealth } from '../services/health'
import { statusItems } from './StatusBar'
import { LOG_LIMIT, addToLog, type LogEntry } from './TranscriptLog'

describe('addToLog', () => {
  test("puts each reply's sentences together, between Pandora's messages and notices", () => {
    let log: LogEntry[] = []
    log = addToLog(log, { type: 'transcript', role: 'admin', text: 'Hi Mika!' })
    log = addToLog(log, { type: 'transcript', role: 'mika', text: 'Hello, Pandora!' })
    log = addToLog(log, { type: 'transcript', role: 'mika', text: 'How was your day?' })
    log = addToLog(log, { type: 'notice', text: "The Mac isn't reachable." })
    log = addToLog(log, { type: 'transcript', role: 'mika', text: 'Oops.' })
    expect(log).toEqual([
      { id: 1, kind: 'admin', text: 'Hi Mika!' },
      { id: 2, kind: 'mika', text: 'Hello, Pandora! How was your day?' },
      { id: 3, kind: 'notice', text: "The Mac isn't reachable." },
      { id: 4, kind: 'mika', text: 'Oops.' },
    ])
  })

  test(`keeps the last ${LOG_LIMIT} entries`, () => {
    let log: LogEntry[] = []
    for (let i = 0; i < LOG_LIMIT + 5; i++) log = addToLog(log, { type: 'notice', text: `notice ${i}` })
    expect(log).toHaveLength(LOG_LIMIT)
    expect(log[0].text).toBe('notice 5')
    expect(log.at(-1)!.id).toBe(LOG_LIMIT + 5)
  })
})

describe('statusItems', () => {
  const health: ClientHealth = {
    status: 'ok',
    mac: 'connected',
    parts: { tts: 'ready', stt: 'starting', avatar_page: 'ready', admin_page: 'ready' },
    pages: { avatar: 1, admin: 1 },
    microphone: 'muted',
  }

  test('says when the client is down or starting', () => {
    expect(statusItems('closed', null)).toEqual([{ label: 'Acer client', value: 'not running', tone: 'bad' }])
    expect(statusItems('connecting', 'starting')).toEqual([{ label: 'Acer client', value: 'starting', tone: 'busy' }])
  })

  test("shows the Mac, the client's parts and the pages", () => {
    expect(statusItems('open', health).map(({ label, value, tone }) => `${label}: ${value} (${tone})`)).toEqual([
      'Acer client: connected (good)',
      'Mac: connected (good)',
      'Voice: ready (good)',
      'Listening: starting (busy)',
      'Microphone: muted (busy)',
      'Avatar page: open (good)',
    ])
    const trouble = statusItems('open', { ...health, mac: 'not connected', parts: { tts: 'error' }, pages: { avatar: 2, admin: 1 } })
    expect(trouble.map((item) => item.tone)).toEqual(['good', 'bad', 'bad', 'busy', 'busy', 'busy'])
    expect(trouble.at(-1)!.value).toBe('open 2 times')
  })
})
