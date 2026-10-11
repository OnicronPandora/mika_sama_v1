// Mika's Live2D model filling the page (Phase 8's avatar): her expression follows `emotion`, her mouth follows
// what `analyser` hears, and `view` says which part of her fills the page.
import { useEffect, useRef, useState } from 'react'
import type { Avatar } from '../live2d/avatar'
import { loadCubismCore } from '../live2d/core'
import { startLipsync } from '../audio/lipsync'
import type { Emotion } from '../types/events'

export interface StageView {
  top: number
  bottom: number
}

interface Props {
  emotion: Emotion
  analyser: AnalyserNode | null
  view: StageView
  onError(message: string): void
}

export function Live2DStage({ emotion, analyser, view, onError }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const [avatar, setAvatar] = useState<Avatar | null>(null)

  useEffect(() => {
    // A canvas of its own: PixiJS ties a WebGL context to it.
    const canvas = document.createElement('canvas')
    container.current!.append(canvas)
    let loaded: Avatar | null = null
    let cancelled = false
    loadCubismCore()
      .then(() => import('../live2d/avatar'))
      .then(({ createAvatar }) => createAvatar(canvas))
      .then(
        (created) => {
          if (cancelled) return created.destroy()
          setAvatar((loaded = created))
          Object.assign(window, { avatar: created }) // for the browser console
        },
        (err: unknown) => {
          if (!cancelled) onError(err instanceof Error ? err.message : String(err))
        },
      )
    return () => {
      cancelled = true
      loaded?.destroy()
      canvas.remove()
    }
  }, [onError])

  useEffect(() => avatar?.frame(view.top, view.bottom), [avatar, view.top, view.bottom])
  useEffect(() => avatar?.setEmotion(emotion), [avatar, emotion])
  useEffect(() => (avatar && analyser ? startLipsync(analyser, avatar.setMouth) : undefined), [avatar, analyser])

  return <div ref={container} className="live2d-stage" />
}
