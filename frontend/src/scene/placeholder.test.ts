import type { AnalysisTool } from "@/types"

import {
  demoBannerNote,
  demoBannerVisible,
  savedToolResult,
  summaryFromMeasurement,
} from "@/scene/placeholder"

describe("demo placeholder", () => {
  it("shows the banner for a placeholder or a copied demo pack", () => {
    expect(demoBannerVisible({ placeholder: true })).toBe(true)
    expect(demoBannerVisible({ seeded: true })).toBe(true)
    expect(demoBannerVisible({ placeholder: false })).toBe(false)
    expect(demoBannerVisible(null)).toBe(false)
    expect(demoBannerVisible({})).toBe(false)
  })

  it("keeps the placeholder sentence distinct from the copied pack", () => {
    expect(demoBannerNote({ placeholder: true, placeholder_note: "Drawn." })).toBe(
      "Drawn."
    )
    expect(demoBannerNote({ seeded: true, seed_note: "Copied." })).toBe("Copied.")
    expect(demoBannerNote({ placeholder: true, seed_note: "Copied." })).toContain(
      "not measured"
    )
  })

  it("fills the summary from a saved tool payload", () => {
    const tool = {
      measurement: {
        summary: [
          { label: "Water area", value: "0 km² placeholder" },
          { label: "no value" },
        ],
      },
      briefing_html: "<p>Demo placeholder.</p>",
      overview_url: "/api/scenes/demo/analysis/open-water/overview.png",
    } as AnalysisTool

    const saved = savedToolResult(tool)

    expect(summaryFromMeasurement(saved.measurement)).toEqual([
      { label: "Water area", value: "0 km² placeholder" },
    ])
    expect(saved.briefing_html).toBe("<p>Demo placeholder.</p>")
    expect(saved.overview_url).toContain("/analysis/open-water/")
    expect(summaryFromMeasurement(savedToolResult(null).measurement)).toEqual([])
  })
})
