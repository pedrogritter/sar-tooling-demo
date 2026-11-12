import { summaryFromMeasurement } from "@/scene/placeholder"
import { ANALYSIS_TOOLS } from "@/scene/tools"
import type {
  JobSnapshot,
  Measurement,
  Report,
  ReportPhase,
  ReportSection,
  ReportSectionStatus,
  ReportTextSource,
} from "@/types"

/** The amplitude-change tool. Its partner list is the second-scene picker. */
const AMPLITUDE_CHANGE_ID = "amplitude-change"

const PLAN_KEY = "step:plan"
const WRITE_KEY = "step:write"

/** Statuses that count as a finished tool. A running id is still in progress. */
const FINISHED_STATUSES: ReadonlySet<string> = new Set([
  "done",
  "locked",
  "failed",
])

const REPORT_PHASES: readonly ReportPhase[] = [
  "planning",
  "running",
  "writing",
  "done",
]

const SECTION_STATUSES: readonly ReportSectionStatus[] = [
  "done",
  "waiting",
  "locked",
  "running",
  "failed",
]

/** One block of a stored briefing, read from its small markdown subset. */
export type BriefingBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }

/** One rail row. `note` is set only on the active step, and only while it runs. */
export interface RailStep {
  key: string
  label: string
  status: string
  /** Set when the document has an anchor for this tool. */
  toolId: string | null
  active: boolean
  note: string | null
}

/** A finished measurement in the document: picture, summary rows, and limit. */
export interface FigureView {
  toolId: string
  label: string
  status: string
  imageUrl: string | null
  summary: { label: string; value: string }[]
  limit: string | null
  partnerId: string | null
}

/** A locked, failed, or legacy waiting tool, after the figures. */
export interface HeldView {
  toolId: string
  label: string
  status: string
  /** The belt's lock or failure text. The narrator note is not included. */
  text: string
}

/**
 * Partner scene ids from an unlocked amplitude-change tool on GET .../tools.
 * An empty list, or a locked comparison, hides the picker.
 */
export function eligiblePartners(
  tools: readonly {
    id: string
    locked?: boolean
    partners?: readonly string[] | null
  }[]
): string[] {
  const tool = tools.find((item) => item.id === AMPLITUDE_CHANGE_ID)

  // A locked comparison is not an eligible partner. The picker stays hidden.
  if (!tool || tool.locked || !tool.partners) {
    return []
  }

  return tool.partners.filter((id) => id.trim() !== "")
}

/**
 * The partner Start sends. An empty choice is this scene only, so the body
 * carries null. A chosen scene id is sent as that id.
 */
export function reportPartnerId(choice: string): string | null {
  const id = choice.trim()
  return id.length > 0 ? id : null
}

/**
 * Fill fields an older saved report omits. The server is adding phase, order,
 * synthesis, and progress notes, with the same defaults: a report that already
 * has sections is done, and a missing note is blank so it cannot leak into
 * the document.
 */
export function normalizeReport(raw: unknown): Report {
  if (!isRecord(raw)) {
    return emptyReport("")
  }

  const sections = (
    Array.isArray(raw.sections)
      ? raw.sections.filter(isRecord).map(normalizeSection)
      : []
  ).filter((section) => section.tool_id !== "")
  const synthesis = typeof raw.synthesis_md === "string" ? raw.synthesis_md : ""
  const toolOrder = Array.isArray(raw.tool_order)
    ? raw.tool_order.filter((id): id is string => typeof id === "string")
    : sections.map((section) => section.tool_id)

  return {
    scene_id: typeof raw.scene_id === "string" ? raw.scene_id : "",
    question: typeof raw.question === "string" ? raw.question : "",
    partner_id: typeof raw.partner_id === "string" ? raw.partner_id : null,
    // A file from before this run has no phase. Sections already saved are a
    // finished report. An empty file is done with nothing to show.
    phase: isPhase(raw.phase) ? raw.phase : "done",
    tool_order: toolOrder.filter((id) => id !== ""),
    synthesis_md: synthesis,
    synthesis_source: textSource(raw.synthesis_source),
    sections,
  }
}

/**
 * Which rail row is active.
 *
 * - Plan, while the phase is planning.
 * - Plan, while a job is running and the saved file is still the previous
 *   finished report, or no report has been read yet. The new run has not
 *   published its phase.
 * - While running: the tool whose section status is running. If none is
 *   running, the first id in tool_order with no section yet. If every id
 *   already has a finished section, Write the report.
 * - Write the report, while the phase is writing.
 * - No row, when the phase is done and the job is not running. Narrator
 *   lines are cleared with the active row.
 */
export function activeRailStep(
  report: Report | null,
  jobRunning: boolean
): string | null {
  const phase = livePhase(report, jobRunning)

  if (phase === null || phase === "done") {
    return null
  }

  if (phase === "planning") {
    return PLAN_KEY
  }

  if (phase === "writing") {
    return WRITE_KEY
  }

  const byId = sectionMap(report)
  const order = report?.tool_order ?? []
  const runningId = order.find((id) => byId.get(id)?.status === "running")

  if (runningId) {
    return toolKey(runningId)
  }

  const queued = order.find((id) => !byId.has(id))

  if (queued) {
    return toolKey(queued)
  }

  const unfinished = order.find((id) => {
    const section = byId.get(id)
    return section !== undefined && !FINISHED_STATUSES.has(section.status)
  })

  if (unfinished) {
    return toolKey(unfinished)
  }

  return WRITE_KEY
}

/** Plan, each id in tool_order, then Write the report. */
export function reportRail(
  report: Report | null,
  jobRunning: boolean,
  jobSentence: string
): RailStep[] {
  const phase = livePhase(report, jobRunning)

  if (phase === null) {
    return []
  }

  if (
    phase === "done" &&
    !reportHasDocument(report) &&
    (report?.tool_order.length ?? 0) === 0
  ) {
    return []
  }

  const activeKey = activeRailStep(report, jobRunning)
  const byId = sectionMap(report)
  const steps: RailStep[] = [
    railStep(PLAN_KEY, "Plan", "", null, activeKey, report, jobSentence),
  ]

  for (const toolId of report?.tool_order ?? []) {
    const section = byId.get(toolId)
    steps.push(
      railStep(
        toolKey(toolId),
        toolLabel(toolId),
        section ? statusLabel(section.status) : statusLabel("queued"),
        section && section.status !== "running" ? toolId : null,
        activeKey,
        report,
        jobSentence
      )
    )
  }

  steps.push(
    railStep(
      WRITE_KEY,
      "Write the report",
      "",
      null,
      activeKey,
      report,
      jobSentence
    )
  )

  return steps
}

/**
 * The lead, once the run has finished. Empty until phase is done, so a
 * half-written synthesis is not shown beside the live steps.
 */
export function synthesisText(report: Report | null): string | null {
  if (!report || report.phase !== "done") {
    return null
  }

  const text = report.synthesis_md.trim()
  return text.length > 0 ? text : null
}

/** Done sections in tool order, then any done section the order omitted. */
export function figureViews(report: Report): FigureView[] {
  return sectionsInOrder(report, (section) => section.status === "done").map(
    (section) => ({
      toolId: section.tool_id,
      label: toolLabel(section.tool_id),
      status: statusLabel(section.status),
      imageUrl: section.overview_url,
      summary: summaryFromMeasurement(section.measurement),
      limit: limitSentence(section.measurement),
      partnerId: section.partner_id,
    })
  )
}

/**
 * Locked tools, then failed tools, then a legacy waiting section. Each group
 * follows tool_order. The narrator note is left out.
 */
export function heldViews(report: Report): HeldView[] {
  const locked = heldGroup(report, "locked")
  const failed = heldGroup(report, "failed")
  const waiting = heldGroup(report, "waiting")

  return [...locked, ...failed, ...waiting]
}

/** Finished tools over the ordered set. Locked and failed count as finished. */
export function reportProgress(report: Report | null): {
  completed: number
  total: number
} {
  const order = report?.tool_order ?? []
  const byId = sectionMap(report)
  const completed = order.filter((id) => {
    const status = byId.get(id)?.status
    return status !== undefined && FINISHED_STATUSES.has(status)
  }).length

  return { completed, total: order.length }
}

/** A 0–100 value for the progress bar. An empty order stays at zero. */
export function progressPercent(completed: number, total: number): number {
  if (total <= 0) {
    return 0
  }

  return Math.min(100, Math.round((completed / total) * 100))
}

/** A report the document can show: a lead, or a section that is no longer running. */
export function reportHasDocument(report: Report | null): boolean {
  if (!report) {
    return false
  }

  if (report.synthesis_md.trim() !== "" && report.phase === "done") {
    return true
  }

  return report.sections.some((section) => section.status !== "running")
}

/** The run finished and left something to read or download. */
export function reportIsComplete(report: Report | null): boolean {
  return report?.phase === "done" && reportHasDocument(report)
}

/**
 * Whether a job read means the report should be loaded too. A job that is
 * already done or failed on the first read has still changed the document.
 */
export function shouldLoadReport(status: JobSnapshot["status"]): boolean {
  return status === "running" || status === "done" || status === "failed"
}

/** The belt's label for a tool id, or the id itself when it is not on the belt. */
export function toolLabel(toolId: string): string {
  return ANALYSIS_TOOLS.find((tool) => tool.id === toolId)?.label ?? toolId
}

/** Plain status words. An id with no section yet is Queued. */
const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Measuring",
  done: "Written",
  waiting: "Needs a second scene",
  locked: "Cannot run",
  failed: "Failed",
}

/** What the side pane says for a section or a planned row. */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
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

/**
 * The phase the rail follows. A running job whose file is still the previous
 * done report is treated as planning until the new phase is saved.
 */
function livePhase(
  report: Report | null,
  jobRunning: boolean
): ReportPhase | null {
  if (!report) {
    return jobRunning ? "planning" : null
  }

  if (jobRunning && report.phase === "done") {
    return "planning"
  }

  return report.phase
}

function railStep(
  key: string,
  label: string,
  status: string,
  toolId: string | null,
  activeKey: string | null,
  report: Report | null,
  jobSentence: string
): RailStep {
  const active = key === activeKey

  return {
    key,
    label,
    status,
    toolId,
    active,
    note: active ? narratorLine(report, key, jobSentence) : null,
  }
}

/**
 * The active row prefers that tool's progress note. Plan, Write, and a tool
 * with a blank note use the job sentence. Inactive rows stay quiet.
 */
function narratorLine(
  report: Report | null,
  stepKey: string,
  jobSentence: string
): string | null {
  if (stepKey !== PLAN_KEY && stepKey !== WRITE_KEY) {
    const toolId = stepKey.startsWith("tool:") ? stepKey.slice(5) : stepKey
    const note = sectionMap(report).get(toolId)?.progress_note.trim()

    if (note) {
      return note
    }
  }

  const sentence = jobSentence.trim()
  return sentence.length > 0 ? sentence : null
}

function heldGroup(report: Report, status: ReportSectionStatus): HeldView[] {
  return sectionsInOrder(report, (section) => section.status === status).map(
    (section) => ({
      toolId: section.tool_id,
      label: toolLabel(section.tool_id),
      status: statusLabel(section.status),
      text: section.briefing_md,
    })
  )
}

function sectionsInOrder(
  report: Report,
  include: (section: ReportSection) => boolean
): ReportSection[] {
  const byId = sectionMap(report)
  const rows: ReportSection[] = []
  const seen = new Set<string>()

  for (const toolId of report.tool_order) {
    const section = byId.get(toolId)

    if (section && include(section)) {
      rows.push(section)
      seen.add(toolId)
    }
  }

  for (const section of byId.values()) {
    if (include(section) && !seen.has(section.tool_id)) {
      rows.push(section)
    }
  }

  return rows
}

function sectionMap(report: Report | null): Map<string, ReportSection> {
  const byId = new Map<string, ReportSection>()

  for (const section of report?.sections ?? []) {
    byId.set(section.tool_id, section)
  }

  return byId
}

function toolKey(toolId: string): string {
  return `tool:${toolId}`
}

function limitSentence(measurement: Measurement | null): string | null {
  const limit = measurement?.limit

  if (typeof limit !== "string") {
    return null
  }

  const text = limit.trim()
  return text.length > 0 ? text : null
}

function emptyReport(sceneId: string): Report {
  return {
    scene_id: sceneId,
    question: "",
    partner_id: null,
    phase: "done",
    tool_order: [],
    synthesis_md: "",
    synthesis_source: "belt",
    sections: [],
  }
}

function normalizeSection(raw: Record<string, unknown>): ReportSection {
  const measurement = isRecord(raw.measurement) ? raw.measurement : null

  return {
    tool_id: typeof raw.tool_id === "string" ? raw.tool_id : "",
    status: isSectionStatus(raw.status) ? raw.status : "failed",
    measurement: measurement as Measurement | null,
    briefing_md: typeof raw.briefing_md === "string" ? raw.briefing_md : "",
    briefing_source: textSource(raw.briefing_source),
    overview_url:
      typeof raw.overview_url === "string" ? raw.overview_url : null,
    partner_id: typeof raw.partner_id === "string" ? raw.partner_id : null,
    progress_note:
      typeof raw.progress_note === "string" ? raw.progress_note : "",
  }
}

function textSource(value: unknown): ReportTextSource {
  return value === "model" ? "model" : "belt"
}

function isPhase(value: unknown): value is ReportPhase {
  return REPORT_PHASES.includes(value as ReportPhase)
}

function isSectionStatus(value: unknown): value is ReportSectionStatus {
  return SECTION_STATUSES.includes(value as ReportSectionStatus)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
