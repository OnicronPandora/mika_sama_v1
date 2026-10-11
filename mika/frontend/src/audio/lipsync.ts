// Lipsync from Spike C: the volume of the audio that is playing, read from a Web Audio AnalyserNode, opens the
// mouth. Spike C's values; Phase 9 tunes the gain and smoothing with Mika's real replies.

/** Speech RMS is about 0.05-0.15; times 6, the mouth opens about 0.3-0.9, and peaks reach 1. */
export const LIPSYNC_GAIN = 6
/** How far the mouth moves toward the new opening each frame (1 = no smoothing). */
export const LIPSYNC_SMOOTHING = 0.5

/** Mouth opening (0-1) for one block of samples: their RMS times `gain`, capped at 1. */
export function mouthOpening(samples: Float32Array, gain = LIPSYNC_GAIN): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (const sample of samples) sum += sample * sample
  return Math.min(1, Math.sqrt(sum / samples.length) * gain)
}

/** Drives `setMouth` from what `analyser` hears, every animation frame. The returned function stops it and
 *  closes the mouth. */
export function startLipsync(analyser: AnalyserNode, setMouth: (value: number) => void): () => void {
  const samples = new Float32Array(analyser.fftSize)
  let mouth = 0
  let frame = 0
  const tick = (): void => {
    analyser.getFloatTimeDomainData(samples)
    mouth += (mouthOpening(samples) - mouth) * LIPSYNC_SMOOTHING
    setMouth(mouth)
    frame = requestAnimationFrame(tick)
  }
  tick()
  return () => {
    cancelAnimationFrame(frame)
    setMouth(0)
  }
}
