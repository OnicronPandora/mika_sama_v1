import type { ClientHealth } from '../services/health'
import type { SocketState } from '../services/chatSocket'

interface Props {
  socket: SocketState
  health: ClientHealth | 'starting' | null
}

type Tone = 'good' | 'busy' | 'bad'

interface Item {
  label: string
  value: string
  tone: Tone
}

const PART_TONES: Record<string, Tone> = { ready: 'good', starting: 'busy', error: 'bad', stopped: 'bad' }

/** What the admin page shows about the Acer client and the Mac. */
export function statusItems(socket: SocketState, health: ClientHealth | 'starting' | null): Item[] {
  if (health === null) return [{ label: 'Acer client', value: 'not running', tone: 'bad' }]
  if (health === 'starting') return [{ label: 'Acer client', value: 'starting', tone: 'busy' }]
  const part = (label: string, state: string | undefined): Item => ({
    label,
    value: state ?? 'unknown',
    tone: PART_TONES[state ?? ''] ?? 'busy',
  })
  return [
    { label: 'Acer client', value: socket === 'open' ? 'connected' : socket, tone: socket === 'open' ? 'good' : 'busy' },
    { label: 'Mac', value: health.mac, tone: health.mac === 'connected' ? 'good' : 'bad' },
    part('Voice', health.parts.tts),
    part('Listening', health.parts.stt),
    { label: 'Microphone', value: health.microphone, tone: health.microphone === 'open' ? 'good' : 'busy' },
    {
      label: 'Avatar page',
      value: health.pages.avatar === 1 ? 'open' : health.pages.avatar === 0 ? 'not open' : `open ${health.pages.avatar} times`,
      tone: health.pages.avatar === 1 ? 'good' : health.pages.avatar === 0 ? 'bad' : 'busy',
    },
  ]
}

export function StatusBar({ socket, health }: Props) {
  return (
    <ul className="status-bar">
      {statusItems(socket, health).map((item) => (
        <li key={item.label} className={item.tone}>
          <span className="label">{item.label}</span> {item.value}
        </li>
      ))}
    </ul>
  )
}
