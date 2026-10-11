// One app, one page per path: /avatar for OBS, /admin for Pandora (plan, section 3). No StrictMode: in development
// it mounts every component twice, which would load the Live2D model and open the audio and the socket twice.
import type { JSX } from 'react'
import { createRoot } from 'react-dom/client'
import { AdminPage } from './pages/AdminPage'
import { AvatarPage } from './pages/AvatarPage'
import { HomePage } from './pages/HomePage'

const PAGES: Record<string, { title: string; Page: () => JSX.Element }> = {
  '/avatar': { title: 'Mika-sama: avatar', Page: AvatarPage },
  '/admin': { title: 'Mika-sama: admin', Page: AdminPage },
}

const { title, Page } = PAGES[location.pathname.replace(/\/+$/, '')] ?? { title: 'Mika-sama', Page: HomePage }
document.title = title
createRoot(document.getElementById('root')!).render(<Page />)
