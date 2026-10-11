// /admin: Pandora's chatbox (plan, Phase 9). She types to Mika here and follows the conversation: her messages
// once they reach the Mac, Mika's sentences as the Mac approves them, and notices (the Mac unreachable, a failed
// turn). The bar on top shows how the Acer client and the Mac are doing.
import { useEffect, useRef, useState } from 'react'
import { Chatbox } from '../components/Chatbox'
import { StatusBar } from '../components/StatusBar'
import { TranscriptLog, addToLog, type LogEntry } from '../components/TranscriptLog'
import { HEALTH_POLL_SECONDS } from '../config'
import { ChatSocket, type SocketState } from '../services/chatSocket'
import { fetchHealth, type ClientHealth } from '../services/health'
import './admin.css'

export function AdminPage() {
  const [log, setLog] = useState<LogEntry[]>([])
  const [socketState, setSocketState] = useState<SocketState>('connecting')
  const [health, setHealth] = useState<ClientHealth | 'starting' | null>('starting')
  const socket = useRef<ChatSocket | null>(null)

  useEffect(() => {
    const chat = new ChatSocket('admin', {
      onEvent: (event) => {
        if (event.type === 'transcript' || event.type === 'notice') setLog((entries) => addToLog(entries, event))
      },
      onState: setSocketState,
    })
    socket.current = chat
    return () => chat.close()
  }, [])

  useEffect(() => {
    const stop = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async (): Promise<void> => {
      const latest = await fetchHealth(stop.signal)
      if (stop.signal.aborted) return
      setHealth(latest)
      timer = setTimeout(poll, HEALTH_POLL_SECONDS * 1000)
    }
    void poll()
    return () => {
      stop.abort()
      clearTimeout(timer)
    }
  }, [])

  const send = (message: string): boolean => socket.current?.send({ type: 'admin_message', message }) ?? false

  return (
    <div className="admin-page">
      <header>
        <h1>Mika-sama</h1>
        <StatusBar socket={socketState} health={health} />
      </header>
      <TranscriptLog entries={log} />
      <Chatbox disabled={socketState !== 'open'} onSend={send} />
    </div>
  )
}
