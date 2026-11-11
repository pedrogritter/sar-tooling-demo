import type { AnalysisTool, JobResult, Measurement } from "@/types"

/** The banner is shown only while the open scene is still the drawn placeholder. */
export function demoBannerVisible(
  scene: { placeholder?: boolean } | null
): boolean {
  return scene?.placeholder === true
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
