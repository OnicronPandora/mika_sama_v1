import { useEffect, useRef } from 'react'
import type { Notice, Transcript } from '../types/events'

export interface LogEntry {
  id: number
  kind: 'admin' | 'mika' | 'notice'
  text: string
}

/** The admin page keeps this many entries. */
export const LOG_LIMIT = 300

/** The log with one more line. Mika's sentences arrive one at a time; those of one reply share an entry. */
export function addToLog(log: LogEntry[], event: Transcript | Notice): LogEntry[] {
  const kind: LogEntry['kind'] = event.type === 'notice' ? 'notice' : event.role
  const last = log.at(-1)
  if (kind === 'mika' && last?.kind === 'mika') {
    return [...log.slice(0, -1), { ...last, text: `${last.text} ${event.text}` }]
  }
  return [...log, { id: (last?.id ?? 0) + 1, kind, text: event.text }].slice(-LOG_LIMIT)
}

const SPEAKERS = { admin: 'Pandora', mika: 'Mika', notice: 'Notice' }

/** The conversation, newest at the bottom. It scrolls along unless Pandora has scrolled up to read. */
export function TranscriptLog({ entries }: { entries: LogEntry[] }) {
  const list = useRef<HTMLOListElement>(null)
  const following = useRef(true)

  useEffect(() => {
    if (following.current) list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [entries])

  const scrolled = (): void => {
    const element = list.current!
    following.current = element.scrollHeight - element.scrollTop - element.clientHeight < 40
  }

  return (
    <ol className="transcript-log" ref={list} onScroll={scrolled}>
      {entries.length === 0 && <li className="empty">The conversation shows up here.</li>}
      {entries.map((entry) => (
        <li key={entry.id} className={entry.kind}>
          <span className="speaker">{SPEAKERS[entry.kind]}</span>
          <p>{entry.text}</p>
        </li>
      ))}
    </ol>
  )
}
