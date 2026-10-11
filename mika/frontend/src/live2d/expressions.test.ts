// The expression files in live2d/expressions: one per emotion, each changing only what the avatar allows.
import { describe, expect, test } from 'vitest'
import { EMOTIONS } from './emotions'

const raw = import.meta.glob<string>('../../live2d/expressions/*.exp3.json', {
  query: '?raw',
  import: 'default',
  eager: true,
})
const expressions = Object.entries(raw).map(([path, text]) => ({
  name: path.split('/').pop()!.replace('.exp3.json', ''),
  text,
  json: JSON.parse(text) as { [key: string]: unknown; Parameters: { Id: string; Value: number; Blend: string }[] },
}))

/** The parameters an expression may change, with the model's ranges (read from miku_sample_t04.moc3). */
const RANGES: Record<string, [number, number]> = {
  ParamEyeLOpen: [0, 1],
  ParamEyeROpen: [0, 1],
  ParamEyeLSmile: [0, 1],
  ParamEyeRSmile: [0, 1],
  ParamEyeBallX: [-1, 1],
  ParamEyeBallY: [-1, 1],
  ParamBrowLY: [-1, 1],
  ParamBrowRY: [-1, 1],
  ParamBrowLX: [-1, 1],
  ParamBrowRX: [-1, 1],
  ParamBrowLAngle: [-1, 1],
  ParamBrowRAngle: [-1, 1],
  ParamBrowLForm: [-1, 1],
  ParamBrowRForm: [-1, 1],
  ParamMouthForm: [-1, 1],
  ParamCheek: [0, 1],
}

/** Blends a parameter must use: the idle motions animate these, so an expression replaces their value. */
const BLENDS: Record<string, string[]> = {
  ParamMouthForm: ['Overwrite'],
  ParamEyeLSmile: ['Overwrite'],
  ParamEyeRSmile: ['Overwrite'],
  ParamEyeLOpen: ['Overwrite', 'Multiply'], // Multiply keeps the motion's closed eyes closed
  ParamEyeROpen: ['Overwrite', 'Multiply'],
}

test('there is one expression per emotion', () => {
  expect(expressions.map((e) => e.name).sort()).toEqual([...EMOTIONS].sort())
})

describe.each(expressions)('$name', ({ text, json }) => {
  test('is a Live2D expression that fades in and out within a second', () => {
    expect(Object.keys(json).sort()).toEqual(['FadeInTime', 'FadeOutTime', 'Parameters', 'Type'])
    expect(json.Type).toBe('Live2D Expression')
    for (const fade of [json.FadeInTime, json.FadeOutTime]) {
      expect(fade).toBeGreaterThan(0)
      expect(fade).toBeLessThanOrEqual(1)
    }
  })

  test('never touches the mouth opening, which lipsync owns (spec)', () => {
    expect(json.Parameters.map((p) => p.Id)).not.toContain('ParamMouthOpenY')
  })

  test('changes only the face, within the model ranges', () => {
    const ids = json.Parameters.map((p) => p.Id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const { Id, Value, Blend } of json.Parameters) {
      expect(RANGES, Id).toHaveProperty(Id)
      const [min, max] = RANGES[Id]
      if (Blend === 'Overwrite') {
        expect(Value, Id).toBeGreaterThanOrEqual(min)
        expect(Value, Id).toBeLessThanOrEqual(max)
      } else if (Blend === 'Add') {
        expect(Math.abs(Value), Id).toBeLessThanOrEqual(max - min)
      } else {
        expect(Blend, Id).toBe('Multiply')
        expect(Value, Id).toBeGreaterThanOrEqual(0)
        expect(Value, Id).toBeLessThanOrEqual(1)
      }
      expect(BLENDS[Id] ?? ['Add', 'Multiply', 'Overwrite'], Id).toContain(Blend)
    }
  })

  test("can be read by Cubism's JSON parser: plain ASCII, no exponents", () => {
    expect(text).toMatch(/^[\x20-\x7e\t\r\n]*$/)
    expect(text).not.toMatch(/\d[eE][+-]?\d/)
  })
})
