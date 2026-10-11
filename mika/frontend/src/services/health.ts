// The Acer client's /health (mika/client/app/main.py), shown on the admin page.
import { CLIENT_URL } from '../config'
import type { ClientComponent, ComponentState } from '../types/events'

export interface ClientHealth {
  status: 'ok'
  mac: 'connected' | 'not connected'
  /** The client's parts as it reports them to the Mac (client_status). */
  parts: Partial<Record<ClientComponent, ComponentState>>
  /** How many pages of each kind are connected. */
  pages: Record<'avatar' | 'admin', number>
  microphone: 'muted' | 'open'
}

/** What /health says, 'starting' while the client starts, or null when it isn't running. */
export async function fetchHealth(signal?: AbortSignal): Promise<ClientHealth | 'starting' | null> {
  try {
    const response = await fetch(`${CLIENT_URL}/health`, { signal, cache: 'no-store' })
    const body = (await response.json()) as { status?: string }
    return body.status === 'ok' ? (body as ClientHealth) : 'starting'
  } catch {
    return null
  }
}
