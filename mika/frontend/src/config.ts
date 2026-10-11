// Where the pages find the Acer client (mika/client, ClientSettings.host and .port), and the pages' timings.

/** The client's HTTP address, for /health. */
export const CLIENT_URL = 'http://127.0.0.1:8001'
/** The client's /ws/chat; each page adds ?page=avatar or ?page=admin. */
export const CHAT_URL = 'ws://127.0.0.1:8001/ws/chat'

/** Mika keeps a reply's expression until the next reply, or until she has been quiet this long (Pandora,
 *  2026-10-11): then she is neutral again. */
export const EXPRESSION_HOLD_SECONDS = 5 * 60
/** The avatar page's subtitle stays this long after the reply's last sentence. */
export const SUBTITLE_LINGER_SECONDS = 4
/** The part of the model the avatar page shows, as fractions of its height: the upper body, so that her
 *  expressions read on stream. `/avatar?top=0&bottom=1` shows the whole body. */
export const AVATAR_VIEW = { top: 0.05, bottom: 0.6 }

/** AVATAR_VIEW, or the avatar page URL's own `top` and `bottom` (for an OBS layout) when they make sense. */
export function avatarView(search: string): { top: number; bottom: number } {
  const params = new URLSearchParams(search)
  const top = Number(params.get('top') ?? AVATAR_VIEW.top)
  const bottom = Number(params.get('bottom') ?? AVATAR_VIEW.bottom)
  return top >= 0 && top < bottom && bottom <= 1 ? { top, bottom } : AVATAR_VIEW
}

/** Reconnecting to the client: the first wait, doubled after each failure up to the longest. */
export const RECONNECT_SECONDS = { first: 1, max: 10 }
/** How often the admin page asks the client how its parts are doing. */
export const HEALTH_POLL_SECONDS = 2
