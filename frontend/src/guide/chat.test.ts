import { readFileSync } from "node:fs"

import {
  ASK_LABEL,
  CHAT_LABEL,
  CHAT_PLACEHOLDER,
  CHAT_UNAVAILABLE,
  CLOSE_LABEL,
  SEND_LABEL,
  guideChatTurn,
  openSectionLabel,
  sectionToOpen,
} from "@/guide/chat"

describe("guide chat turn", () => {
  it("keeps the reply and opens a section only when asked", () => {
    const offer = guideChatTurn({
      reply: "Dark smooth water. Open the Open water section?",
      section_id: "tool-open-water",
      section_title: "Open water",
      open_section: false,
    })

    expect(offer.reply).toContain("Open the Open water section?")
    expect(sectionToOpen(offer)).toBeNull()
    expect(openSectionLabel(offer)).toBe("Open Open water")

    const opening = guideChatTurn({
      reply: "Opening Open water.",
      section_id: "tool-open-water",
      section_title: "Open water",
      open_section: true,
    })

    expect(sectionToOpen(opening)).toBe("tool-open-water")
  })

  it("rejects a payload that is not a turn", () => {
    expect(() => guideChatTurn(null)).toThrow(CHAT_UNAVAILABLE)
    expect(() =>
      guideChatTurn({
        reply: "",
        section_id: null,
        section_title: null,
        open_section: false,
      })
    ).toThrow(CHAT_UNAVAILABLE)
  })

  it("uses the fixed labels", () => {
    expect(ASK_LABEL).toBe("Ask")
    expect(CLOSE_LABEL).toBe("Close")
    expect(CHAT_LABEL).toBe("Guide chat")
    expect(CHAT_PLACEHOLDER).toBe("Ask about a tool or about SAR")
    expect(SEND_LABEL).toBe("Send")
  })

  it("does not offer to run a tool or download a scene", () => {
    const view = readFileSync("src/guide/GuideChat.tsx", "utf8")

    expect(view).not.toContain("Download")
    expect(view).not.toContain(">Run<")
    expect(view).not.toContain("startAnalysisJob")
  })
})