/** Normal Chrome only plays audio after a click on the page (OBS doesn't ask), so the avatar page shows this
 *  until it gets one. */
export function AudioUnlock({ onUnlock }: { onUnlock(): void }) {
  return (
    <button className="audio-unlock" onClick={onUnlock}>
      Click to turn on Mika&apos;s voice
    </button>
  )
}
