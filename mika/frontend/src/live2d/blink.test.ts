import { describe, expect, test } from 'vitest'
import { BLINK, BLINK_INTERVAL, blinkClosure, blinker } from './blink'

const END = BLINK.closing + BLINK.closed + BLINK.opening
const CLOSED = BLINK.closing + BLINK.closed / 2 // seconds into a blink, with the eyes shut

describe('blinkClosure', () => {
  test('closes, stays closed, then opens again', () => {
    expect(blinkClosure(-0.01)).toBe(0)
    expect(blinkClosure(0)).toBe(0)
    expect(blinkClosure(BLINK.closing / 2)).toBeCloseTo(0.5)
    expect(blinkClosure(CLOSED)).toBe(1)
    expect(blinkClosure(BLINK.closing + BLINK.closed + BLINK.opening / 2)).toBeCloseTo(0.5)
    expect(blinkClosure(END)).toBe(0)
    expect(blinkClosure(END + 1)).toBe(0)
  })
})

describe('blinker', () => {
  test('blinks after a random interval, then waits a new one', () => {
    const randoms = [0, 1]
    const blink = blinker(() => randoms.shift()!)
    expect(blink(10)).toBe(0) // the first blink starts at 10 + min
    expect(blink(10 + BLINK_INTERVAL.min - 0.01)).toBe(0)
    expect(blink(10 + BLINK_INTERVAL.min + CLOSED)).toBe(1)
    const after = 10 + BLINK_INTERVAL.min + END
    expect(blink(after)).toBe(0) // that blink is over; the next starts max seconds later
    expect(blink(after + BLINK_INTERVAL.max - 0.01)).toBe(0)
    expect(blink(after + BLINK_INTERVAL.max + CLOSED)).toBe(1)
  })

  test('waits between the shortest and the longest interval', () => {
    for (const random of [0, 0.5, 0.999]) {
      const blink = blinker(() => random)
      blink(0)
      const start = BLINK_INTERVAL.min + random * (BLINK_INTERVAL.max - BLINK_INTERVAL.min)
      expect(blink(start - 0.01)).toBe(0)
      expect(blink(start + CLOSED)).toBe(1)
    }
  })
})
