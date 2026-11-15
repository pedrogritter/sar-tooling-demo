/** One guide-chat turn. The sentences stay on the server. */

export const ASK_LABEL = "Ask"
export const CLOSE_LABEL = "Close"
export const CHAT_LABEL = "Guide chat"
export const CHAT_PLACEHOLDER = "Ask about a tool or about SAR"
export const SEND_LABEL = "Send"
export const CHAT_UNAVAILABLE = "The guide chat could not answer."

export interface GuideChatTurn {
  reply: string
  sectionId: string | null
  sectionTitle: string | null
  openSection: boolean
}

export function guideChatTurn(payload: unknown): GuideChatTurn {
  if (!isRecord(payload) || typeof payload.reply !== "string") {
    throw new Error(CHAT_UNAVAILABLE)
  }

  if (payload.reply.trim() === "") {
    throw new Error(CHAT_UNAVAILABLE)
  }

  if (typeof payload.open_section !== "boolean") {
    throw new Error(CHAT_UNAVAILABLE)
  }

  return {
    reply: payload.reply,
    sectionId: optionalText(payload.section_id),
    sectionTitle: optionalText(payload.section_title),
    openSection: payload.open_section,
  }
}

export function sectionToOpen(turn: GuideChatTurn): string | null {
  if (turn.openSection && turn.sectionId) {
    return turn.sectionId
  }

  return null
}

export function openSectionLabel(turn: GuideChatTurn): string | null {
  if (!turn.sectionId || !turn.sectionTitle || turn.openSection) {
    return null
  }

  return `Open ${turn.sectionTitle}`
}

function optionalText(value: unknown): string | null {
  if (value === null) {
    return null
  }

  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(CHAT_UNAVAILABLE)
  }

  return value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}