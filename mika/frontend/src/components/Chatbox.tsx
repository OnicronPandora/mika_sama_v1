import { useState, type FormEvent, type KeyboardEvent } from 'react'

interface Props {
  disabled: boolean
  /** Returns false if the message couldn't be sent; the text then stays in the box. */
  onSend(message: string): boolean
}

/** Pandora's message box: Enter sends, Shift+Enter starts a new line. */
export function Chatbox({ disabled, onSend }: Props) {
  const [text, setText] = useState('')

  const send = (): void => {
    const message = text.trim()
    if (message && onSend(message)) setText('')
  }
  const submit = (event: FormEvent): void => {
    event.preventDefault()
    send()
  }
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    // isComposing: Enter that confirms an input method's candidate (Vietnamese, Japanese...) doesn't send
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }

  return (
    <form className="chatbox" onSubmit={submit}>
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={keyDown}
        placeholder={disabled ? 'Waiting for the Acer client…' : 'Say something to Mika'}
        rows={2}
        autoFocus
      />
      <button type="submit" disabled={disabled || !text.trim()}>
        Send
      </button>
    </form>
  )
}
