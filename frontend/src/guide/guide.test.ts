import { readFileSync } from "node:fs"

import {
  GUIDE_CONTENTS_LABEL,
  GUIDE_HEADING,
  GUIDE_LOADING,
  GUIDE_UNAVAILABLE,
  contentsEntries,
  guideDocument,
} from "@/guide/guide"

describe("usage guide document", () => {
  const payload = {
    sections: [
      {
        id: "what-this-is",
        title: "What this application does",
        paragraphs: ["A bright mark is a bright radar return."],
      },
      {
        id: "tool-open-water",
        title: "Open water",
        paragraphs: ["Dark smooth water.", "Limit sentence."],
      },
    ],
  }

  it("keeps id, title, and paragraphs", () => {
    const document = guideDocument(payload)

    expect(contentsEntries(document)).toEqual([
      { id: "what-this-is", title: "What this application does" },
      { id: "tool-open-water", title: "Open water" },
    ])
    expect(document.sections[1]?.paragraphs).toEqual([
      "Dark smooth water.",
      "Limit sentence.",
    ])
  })

  it("rejects a payload that is not the guide", () => {
    expect(() => guideDocument(null)).toThrow(GUIDE_UNAVAILABLE)
    expect(() => guideDocument({ sections: [] })).toThrow(GUIDE_UNAVAILABLE)
    expect(() =>
      guideDocument({
        sections: [{ id: "what-this-is", title: "Title", paragraphs: [""] }],
      })
    ).toThrow(GUIDE_UNAVAILABLE)
    expect(() =>
      guideDocument({ sections: [{ id: "", title: "Title", paragraphs: ["Ok."] }] })
    ).toThrow(GUIDE_UNAVAILABLE)
  })

  it("uses the fixed heading and loading copy", () => {
    expect(GUIDE_LOADING).toBe("Opening the usage guide.")
    expect(GUIDE_HEADING).toBe("Documentation")
    expect(GUIDE_CONTENTS_LABEL).toBe("In this guide")
  })

  it("does not copy a toolkit limit into the guide modules", () => {
    const guide = readFileSync("src/guide/guide.ts", "utf8")
    const view = readFileSync("src/guide/DocumentationView.tsx", "utf8")

    expect(guide).not.toContain("Shadow, tarmac")
    expect(view).not.toContain("Shadow, tarmac")
    expect(view).not.toContain("building height")
  })
})