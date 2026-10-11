import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Emotion } from '../types/events'
import { ExpressionHold } from './expressionHold'

const MINUTE = 60_000
const HOLD_SECONDS = 5 * 60

let shown: Emotion[]
let hold: ExpressionHold

beforeEach(() => {
  vi.useFakeTimers()
  shown = []
  hold = new ExpressionHold((emotion) => shown.push(emotion), HOLD_SECONDS)
})

afterEach(() => {
  hold.close()
  vi.useRealTimers()
})

test("keeps a reply's expression, then goes back to neutral after five quiet minutes", () => {
  hold.show('sad')
  vi.advanceTimersByTime(5 * MINUTE - 1)
  expect(shown).toEqual(['sad'])
  vi.advanceTimersByTime(1)
  expect(shown).toEqual(['sad', 'neutral'])
})

test('the quiet time counts from when she last talked', () => {
  hold.show('angry')
  vi.advanceTimersByTime(4 * MINUTE)
  hold.touch()
  vi.advanceTimersByTime(4 * MINUTE)
  expect(shown).toEqual(['angry'])
  vi.advanceTimersByTime(MINUTE)
  expect(shown).toEqual(['angry', 'neutral'])
})

test('the next reply replaces the expression and starts the time again', () => {
  hold.show('happy')
  vi.advanceTimersByTime(3 * MINUTE)
  hold.show('confused')
  vi.advanceTimersByTime(3 * MINUTE)
  expect(shown).toEqual(['happy', 'confused'])
  vi.advanceTimersByTime(2 * MINUTE)
  expect(shown).toEqual(['happy', 'confused', 'neutral'])
})

test('neutral has nothing to go back from', () => {
  hold.show('neutral')
  hold.touch()
  vi.advanceTimersByTime(60 * MINUTE)
  expect(shown).toEqual(['neutral'])
})

test('close() cancels the wait', () => {
  hold.show('sad')
  hold.close()
  vi.advanceTimersByTime(60 * MINUTE)
  expect(shown).toEqual(['sad'])
})
