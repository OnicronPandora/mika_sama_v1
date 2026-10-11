import { afterEach, describe, expect, test, vi } from 'vitest'
import { LIPSYNC_GAIN, LIPSYNC_SMOOTHING, mouthOpening, startLipsync } from './lipsync'

describe('mouthOpening', () => {
  test('is the RMS times the gain, capped at 1', () => {
    expect(mouthOpening(new Float32Array(512))).toBe(0)
    expect(mouthOpening(new Float32Array(512).fill(0.1))).toBeCloseTo(0.1 * LIPSYNC_GAIN)
    expect(mouthOpening(new Float32Array([0.1, -0.1, 0.1, -0.1]))).toBeCloseTo(0.1 * LIPSYNC_GAIN)
    expect(mouthOpening(new Float32Array(512).fill(0.5))).toBe(1)
    expect(mouthOpening(new Float32Array(512).fill(0.1), 2)).toBeCloseTo(0.2)
    expect(mouthOpening(new Float32Array(0))).toBe(0)
  })
})

describe('startLipsync', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('follows the audio every frame, smoothed, and closes the mouth when stopped', () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback))
    const cancelAnimationFrame = vi.fn()
    vi.stubGlobal('cancelAnimationFrame', cancelAnimationFrame)
    let level = 0.1
    const analyser = {
      fftSize: 256,
      getFloatTimeDomainData: (samples: Float32Array) => samples.fill(level),
    } as unknown as AnalyserNode
    const mouth: number[] = []

    const stop = startLipsync(analyser, (value) => mouth.push(value))
    frames.shift()!(0)
    const target = 0.1 * LIPSYNC_GAIN
    expect(mouth[0]).toBeCloseTo(target * LIPSYNC_SMOOTHING) // the first frame runs at once
    expect(mouth[1]).toBeCloseTo(target * (1 - (1 - LIPSYNC_SMOOTHING) ** 2))
    level = 0 // a pause: the mouth closes over a few frames
    for (let i = 0; i < 10; i++) frames.shift()!(0)
    expect(mouth.at(-1)).toBeLessThan(0.01)

    stop()
    expect(cancelAnimationFrame).toHaveBeenCalledOnce()
    expect(mouth.at(-1)).toBe(0)
  })
})
