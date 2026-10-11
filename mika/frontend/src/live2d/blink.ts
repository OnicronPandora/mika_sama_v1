// Mika blinks every few seconds. The model's idle motions never blink: they close her eyes in a smile (^^),
// most of the time. The expressions other than happy cancel that and keep her eyes open, so blinking happens
// here, on top of whatever the motion and the expression make of her eyes.

/** Cubism's own eye blink timings (CubismEyeBlink), in seconds. */
export const BLINK = { closing: 0.1, closed: 0.05, opening: 0.15 }
/** Seconds from the end of one blink to the start of the next, picked at random in this range. */
export const BLINK_INTERVAL = { min: 2, max: 6 }

const BLINK_SECONDS = BLINK.closing + BLINK.closed + BLINK.opening

/** How closed a blink has the eyes `t` seconds after it starts: 0 open, 1 closed. */
export function blinkClosure(t: number): number {
  if (t < 0 || t >= BLINK_SECONDS) return 0
  if (t < BLINK.closing) return t / BLINK.closing
  if (t < BLINK.closing + BLINK.closed) return 1
  return 1 - (t - BLINK.closing - BLINK.closed) / BLINK.opening
}

/** Returns a function to call every frame with the time in seconds; it answers how closed the eyes are. */
export function blinker(random: () => number = Math.random): (now: number) => number {
  const interval = (): number => BLINK_INTERVAL.min + random() * (BLINK_INTERVAL.max - BLINK_INTERVAL.min)
  let start: number | null = null
  return (now) => {
    start ??= now + interval()
    if (now - start >= BLINK_SECONDS) start = now + interval()
    return blinkClosure(now - start)
  }
}
