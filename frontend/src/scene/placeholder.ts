import type { AnalysisTool, JobResult, Measurement } from "@/types"

const PLACEHOLDER_FALLBACK =
  "Demo placeholder. These pictures and numbers were not measured from an ICEYE raster."
const SEEDED_FALLBACK =
  "Demo data copied from the Lisbon pack. The radar products are not in this folder."

interface DemoBannerScene {
  placeholder?: boolean
  placeholder_note?: string | null
  seeded?: boolean
  seed_note?: string | null
}

/** The banner is shown for a drawn placeholder or a copied Lisbon demo pack. */
export function demoBannerVisible(scene: DemoBannerScene | null): boolean {
  return scene?.placeholder === true || scene?.seeded === true
}

/** Sentence in the banner. A placeholder keeps its own wording. */
export function demoBannerNote(scene: DemoBannerScene | null): string {
  if (scene?.placeholder === true) {
    const note = scene.placeholder_note?.trim()
    return note || PLACEHOLDER_FALLBACK
  }
  const note = scene?.seed_note?.trim()
  return note || SEEDED_FALLBACK
}

/** Picture, summary, and briefing already stored for a tool. */
export function savedToolResult(tool: AnalysisTool | null): JobResult {
  return {
    measurement: tool?.measurement ?? null,
    briefing_html: tool?.briefing_html ?? null,
    overview_url: tool?.overview_url ?? null,
  }
}

export function summaryFromMeasurement(
  measurement: Measurement | null
): { label: string; value: string }[] {
  const summary = measurement?.summary
  if (!Array.isArray(summary)) {
    return []
  }

  return summary.flatMap((row) => {
    if (!row || typeof row.label !== "string" || typeof row.value !== "string") {
      return []
    }

    return [{ label: row.label, value: row.value }]
  })
}
