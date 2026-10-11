// /avatar: Mika, for OBS (a browser source) or Chrome. Her expression follows each reply's emotion, her voice plays
// here with lipsync, and each sentence shows as a subtitle while it plays (plan, Phase 9).
import { useEffect, useMemo, useState } from 'react'
import { WebAudioOutput } from '../audio/output'
import { PlaybackQueue } from '../audio/playbackQueue'
import { AudioUnlock } from '../components/AudioUnlock'
import { Live2DStage } from '../components/Live2DStage'
import { TranscriptOverlay } from '../components/TranscriptOverlay'
import { EXPRESSION_HOLD_SECONDS, SUBTITLE_LINGER_SECONDS, avatarView } from '../config'
import { ExpressionHold } from '../live2d/expressionHold'
import { ChatSocket } from '../services/chatSocket'
import type { Emotion } from '../types/events'
import './avatar.css'

export function AvatarPage() {
  const view = useMemo(() => avatarView(location.search), [])
  const [emotion, setEmotion] = useState<Emotion>('neutral')
  const [subtitle, setSubtitle] = useState({ text: '', visible: false })
  const [audio, setAudio] = useState<WebAudioOutput | null>(null)
  const [audioLocked, setAudioLocked] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const output = new WebAudioOutput()
    const lockChanged = (): void => setAudioLocked(!output.unlocked)
    output.onChange(lockChanged)
    lockChanged()
    setAudio(output)
    Object.assign(window, { audio: output }) // for the browser console

    const hold = new ExpressionHold(setEmotion, EXPRESSION_HOLD_SECONDS)
    let hideSubtitle: ReturnType<typeof setTimeout> | undefined
    let socket: ChatSocket | undefined
    const queue = new PlaybackQueue(output, {
      emotion: (next) => hold.show(next),
      sentence: (text) => {
        clearTimeout(hideSubtitle)
        setSubtitle({ text, visible: true })
      },
      turnOver: () => {
        hold.touch()
        clearTimeout(hideSubtitle)
        hideSubtitle = setTimeout(
          () => setSubtitle((shown) => ({ ...shown, visible: false })),
          SUBTITLE_LINGER_SECONDS * 1000,
        )
      },
      report: (event) => socket?.send(event),
    })
    socket = new ChatSocket('avatar', {
      onEvent: (event) => {
        if (event.type === 'emotion' || event.type === 'audio_chunk' || event.type === 'turn_end') queue.push(event)
      },
    })
    return () => {
      socket?.close()
      queue.close()
      hold.close()
      clearTimeout(hideSubtitle)
      output.close()
    }
  }, [])

  return (
    <div className="avatar-page">
      <Live2DStage emotion={emotion} analyser={audio?.analyser ?? null} view={view} onError={setError} />
      <TranscriptOverlay text={subtitle.text} visible={subtitle.visible} />
      {audio && audioLocked && <AudioUnlock onUnlock={() => void audio.unlock()} />}
      {error && <p className="avatar-error">{error}</p>}
    </div>
  )
}
