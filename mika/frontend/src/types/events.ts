// Generated from mika/shared by `python -m mika_shared.codegen_ts --write`. Do not edit by hand.

// ---- Enums ----

/** Mika's emotion for one reply, read from the reply's leading [emotion] tag. */
export type Emotion = 'happy' | 'sad' | 'confused' | 'angry' | 'neutral';

/** Set by the system for each turn, never by the LLM. */
export type Intent = 'casual_conversation' | 'filter_incident' | 'error_recovery';

/** The output filter's verdict for one sentence. */
export type FilterAction = 'ALLOW' | 'REPLACE' | 'BLOCK';

/** Where a user message came from. */
export type MessageSource = 'chat' | 'voice';

/** Who said a transcript line. */
export type TranscriptRole = 'admin' | 'mika';

/** A part of the Acer side that reports its health to the Mac. */
export type ClientComponent = 'tts' | 'stt' | 'avatar_page' | 'admin_page';

/** Health of one client component. */
export type ComponentState = 'starting' | 'ready' | 'error' | 'stopped';

// ---- /ws/runtime: Acer -> Mac ----

/** The only request payload. Admin input (chatbox and voice) uses user_id "admin". */
export interface UserMessage {
  type: 'user_message';
  user_id: string;
  message: string;
  source: MessageSource;
}

/** Health update from the Acer: TTS ready, STT ready, avatar page connected, and so on. */
export interface ClientStatus {
  type: 'client_status';
  component: ClientComponent;
  status: ComponentState;
  detail?: string | null;
}

// ---- /ws/runtime: Mac -> Acer ----

/** Sent as soon as the reply's emotion tag is parsed. The Acer mutes STT and forwards the emotion. */
export interface TurnStart {
  type: 'turn_start';
  turn_id: string;
  emotion: Emotion;
}

/** One approved sentence, sent in spoken order. */
export interface Sentence {
  type: 'sentence';
  turn_id: string;
  /** 0-based position of the sentence in the spoken order. */
  seq: number;
  text: string;
  action: FilterAction;
}

/** No more sentences for this turn. */
export interface TurnEnd {
  type: 'turn_end';
  turn_id: string;
  /** seq of the turn's last sentence; null when the turn produced no sentences. */
  last_seq: number | null;
  intent: Intent;
}

/** The turn failed. The Acer unmutes STT. */
export interface TurnError {
  type: 'error';
  /** null when the error is not tied to a turn. */
  turn_id?: string | null;
  message: string;
}

// ---- /ws/chat: browser -> Acer ----

/** Typed in the admin chatbox. The Acer forwards it as a user_message with user_id "admin". */
export interface AdminMessage {
  type: 'admin_message';
  message: string;
}

/** The avatar page started playing a sentence's audio. */
export interface PlaybackStarted {
  type: 'playback_started';
  turn_id: string;
  /** 0-based position of the sentence in the spoken order. */
  seq: number;
}

/** The avatar page finished a sentence's audio. At the turn's last_seq, the Acer unmutes STT. */
export interface PlaybackFinished {
  type: 'playback_finished';
  turn_id: string;
  /** 0-based position of the sentence in the spoken order. */
  seq: number;
}

// ---- /ws/chat: Acer -> browser ----

/** Switch the avatar's expression for this turn. */
export interface EmotionUpdate {
  type: 'emotion';
  turn_id: string;
  emotion: Emotion;
}

/** One spoken sentence: its audio and its transcript line. */
export interface AudioChunk {
  type: 'audio_chunk';
  turn_id: string;
  /** 0-based position of the sentence in the spoken order. */
  seq: number;
  text: string;
  /** A complete WAV file, base64-encoded. */
  audio_b64: string;
  sample_rate: number;
}

/** Tells the avatar page that the reply is complete. */
export interface ChatTurnEnd {
  type: 'turn_end';
  turn_id: string;
  /** seq of the turn's last sentence; null when the turn produced no sentences. */
  last_seq: number | null;
}

/** One line for the admin page's chat log. */
export interface Transcript {
  type: 'transcript';
  role: TranscriptRole;
  text: string;
}

// ---- One union per channel direction ----

/** /ws/runtime: Acer -> Mac */
export type RuntimeClientEvent = UserMessage | ClientStatus;

/** /ws/runtime: Mac -> Acer */
export type RuntimeServerEvent = TurnStart | Sentence | TurnEnd | TurnError;

/** /ws/chat: browser -> Acer */
export type ChatClientEvent = AdminMessage | PlaybackStarted | PlaybackFinished;

/** /ws/chat: Acer -> browser */
export type ChatServerEvent = EmotionUpdate | AudioChunk | ChatTurnEnd | Transcript;
