import './admin.css'

/** `/`: where the pages are. */
export function HomePage() {
  return (
    <main className="home-page">
      <h1>Mika-sama</h1>
      <ul>
        <li>
          <a href="/avatar">Avatar</a>: Mika, her voice and her subtitles. In OBS, add it as a browser source.
        </li>
        <li>
          <a href="/admin">Admin</a>: the chatbox and the conversation.
        </li>
        <li>
          <a href="/check.html">Avatar check</a>: each expression, and lipsync with it.
        </li>
      </ul>
    </main>
  )
}
