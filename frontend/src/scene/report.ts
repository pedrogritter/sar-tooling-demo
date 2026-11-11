import { ANALYSIS_TOOLS } from "@/scene/tools"
import type {
  Report,
  ReportLockedTool,
  ReportPlan,
  ReportSection,
} from "@/types"

/** One block of a stored briefing, read from its small markdown subset. */
export type BriefingBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }

/** The three groups of the plan the server returns. */
export interface PlanSplit {
  /** Unlocked tools that run now. */
  selected: string[]
  /** Tools that wait for an analyst choice (amplitude change). */
  waiting: string[]
  /** Tools the belt keeps locked, each with the belt's own reason. */
  locked: ReportLockedTool[]
}

/**
 * Split the plan JSON from `POST .../report/plan` into its three groups.
 * The keys match `ReportPlan` in `src/scene/report/schema.py`. Any other shape
 * throws, so a server change fails here and not as an empty page.
 */
export function splitPlan(plan: ReportPlan): PlanSplit {
  if (
    !isStringList(plan.selected) ||
    !isStringList(plan.waiting) ||
    !Array.isArray(plan.locked) ||
    !plan.locked.every(isLockedTool)
  ) {
    throw new Error("The report plan from the server has an unexpected shape.")
  }

  return {
    selected: [...plan.selected],
    waiting: [...plan.waiting],
    locked: plan.locked.map((tool) => ({ id: tool.id, reason: tool.reason })),
  }
}

/**
 * The tool ids Compile posts: what runs now and what waits. A locked id is
 * dropped even if it also appears in `selected`, because the server refuses it.
 */
export function runnableIds(plan: ReportPlan): string[] {
  const split = splitPlan(plan)
  const locked = new Set(split.locked.map((tool) => tool.id))

  return [...split.selected, ...split.waiting].filter((id) => !locked.has(id))
}

/**
 * The stored briefing when it is the belt's own text, else null.
 * A belt briefing keeps the limit string, so it is shown as stored.
 */
export function beltText(section: ReportSection): string | null {
  return section.briefing_source === "belt" ? section.briefing_md : null
}

/**
 * Partners offered for amplitude change: the one the plan lists, or, when the
 * plan lists none, the partners the scene's tool list gives.
 */
export function partnerOptions(
  plan: ReportPlan | null,
  toolPartners: readonly string[]
): string[] {
  if (plan?.partner_id) {
    return [plan.partner_id]
  }

  return [...toolPartners]
}

/**
 * The sections that failed. A finished job does not mean every section
 * succeeded, so the page reads this and not the job status.
 */
export function failedSections(report: Report): ReportSection[] {
  return report.sections.filter((section) => section.status === "failed")
}

/** The belt's label for a tool id, or the id itself when it is not on the belt. */
export function toolLabel(toolId: string): string {
  return ANALYSIS_TOOLS.find((tool) => tool.id === toolId)?.label ?? toolId
}

/**
 * Read a stored briefing as headings, paragraphs, and bullet lists. The belt
 * writes only those three, so nothing else is interpreted and the text is
 * never inserted as HTML.
 */
export function briefingBlocks(markdown: string): BriefingBlock[] {
  const blocks: BriefingBlock[] = []
  let paragraph: string[] = []
  let items: string[] = []

  const flush = () => {
    if (paragraph.length > 0) {
      blocks.push({ kind: "paragraph", text: paragraph.join(" ") })
      paragraph = []
    }

    if (items.length > 0) {
      blocks.push({ kind: "list", items })
      items = []
    }
  }

  for (const raw of markdown.split("\n")) {
    const line = raw.trim()
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    const bullet = /^[-*]\s+(.*)$/.exec(line)

    if (!line) {
      flush()
    } else if (heading) {
      flush()
      blocks.push({ kind: "heading", text: heading[1] })
    } else if (bullet) {
      if (paragraph.length > 0) {
        flush()
      }
      items.push(bullet[1])
    } else {
      if (items.length > 0) {
        flush()
      }
      paragraph.push(line)
    }
  }

  flush()
  return blocks
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

function isLockedTool(value: unknown): value is ReportLockedTool {
  if (typeof value !== "object" || value === null) {
    return false
  }

  const candidate = value as { id?: unknown; reason?: unknown }

  return (
    typeof candidate.id === "string" &&
    (typeof candidate.reason === "string" || candidate.reason === null)
  )
}
