"""Contracts shared by the Mika-sama server (Mac M1), client (Acer) and frontend.

- enums: Emotion, Intent, FilterAction and the small enums the events use
- payloads: UserRequest, FilterResult, TurnResult (from the spec)
- events: every WebSocket event (implementation plan, section 5)
- codegen_ts: writes the matching TypeScript types for the frontend
"""
