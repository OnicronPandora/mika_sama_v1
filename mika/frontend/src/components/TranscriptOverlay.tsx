/** The avatar page's subtitle: the sentence Mika is saying, shown when its audio starts (spec). */
export function TranscriptOverlay({ text, visible }: { text: string; visible: boolean }) {
  return (
    <div className={visible ? 'subtitle visible' : 'subtitle'} aria-live="polite">
      {text}
    </div>
  )
}
