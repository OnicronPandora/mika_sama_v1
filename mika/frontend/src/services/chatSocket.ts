// The pages' connection to the Acer client's /ws/chat (plan, section 5.2). It keeps reconnecting: the client may
// start after the page, or restart while OBS keeps the page open.
import { CHAT_URL, RECONNECT_SECONDS } from '../config'
import type { ChatClientEvent, ChatServerEvent } from '../types/events'

export type PageKind = 'avatar' | 'admin'
export type SocketState = 'connecting' | 'open' | 'closed'

const OPEN = 1 // WebSocket.OPEN
const SERVER_EVENTS: ReadonlySet<string> = new Set<ChatServerEvent['type']>([
  'emotion',
  'audio_chunk',
  'turn_end',
  'transcript',
  'notice',
])

/** The event in a message from the client, or null for anything else. The client validates what it sends
 *  against the shared contracts, so only the type is checked here. */
export function parseChatServerEvent(data: unknown): ChatServerEvent | null {
  if (typeof data !== 'string') return null
  try {
    const event: unknown = JSON.parse(data)
    if (typeof event === 'object' && event !== null && SERVER_EVENTS.has((event as { type?: unknown }).type as string)) {
      return event as ChatServerEvent
    }
  } catch {
    // not JSON
  }
  return null
}

export interface ChatSocketOptions {
  onEvent(event: ChatServerEvent): void
  onState?(state: SocketState): void
  url?: string
  /** For tests. */
  createSocket?(url: string): WebSocket
}

export class ChatSocket {
  private readonly url: string
  private socket: WebSocket | null = null
  private retry: ReturnType<typeof setTimeout> | undefined
  private delay = RECONNECT_SECONDS.first
  private closed = false

  constructor(
    page: PageKind,
    private readonly options: ChatSocketOptions,
  ) {
    this.url = `${options.url ?? CHAT_URL}?page=${page}`
    this.connect()
  }

  get isOpen(): boolean {
    return this.socket?.readyState === OPEN
  }

  /** Sends the event if the client is connected; false if it isn't (nothing is queued). */
  send(event: ChatClientEvent): boolean {
    if (!this.socket || this.socket.readyState !== OPEN) return false
    this.socket.send(JSON.stringify(event))
    return true
  }

  /** Disconnects for good. */
  close(): void {
    this.closed = true
    clearTimeout(this.retry)
    this.socket?.close()
  }

  private connect(): void {
    this.options.onState?.('connecting')
    const socket = this.options.createSocket ? this.options.createSocket(this.url) : new WebSocket(this.url)
    this.socket = socket
    socket.onopen = () => {
      this.delay = RECONNECT_SECONDS.first
      this.options.onState?.('open')
    }
    socket.onmessage = (message: MessageEvent) => {
      const event = parseChatServerEvent(message.data)
      if (event) this.options.onEvent(event)
      else console.warn('Ignored a message from the client:', message.data)
    }
    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = null
      this.options.onState?.('closed')
      if (this.closed) return
      this.retry = setTimeout(() => this.connect(), this.delay * 1000)
      this.delay = Math.min(this.delay * 2, RECONNECT_SECONDS.max)
    }
  }
}
