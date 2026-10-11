import type { Emotion } from '../types/events'

// Every emotion of the shared schema, in its order; type checking fails if one is missing or extra.
const ALL: Record<Emotion, true> = { happy: true, sad: true, confused: true, angry: true, neutral: true }

/** Each one has an expression in live2d/expressions/<emotion>.exp3.json, registered under its name. */
export const EMOTIONS = Object.keys(ALL) as Emotion[]
