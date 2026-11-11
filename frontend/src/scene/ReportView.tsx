import { useCallback, useEffect, useState } from "react"

import {
  ApiError,
  MeasureJobConflictError,
  fetchAnalysisTools,
  fetchCurrentJob,
  fetchReport,
  planReport,
  reportPdfUrl,
  startReportAmplitude,
  startReportRun,
} from "@/api"
import { Button, buttonVariants } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { summaryFromMeasurement } from "@/scene/placeholder"
import {
  beltText,
  briefingBlocks,
  failedSections,
  partnerOptions,
  runnableIds,
  splitPlan,
  toolLabel,
} from "@/scene/report"
import type {
  AnalysisTool,
  JobSnapshot,
  Report,
  ReportPlan,
  ReportSection,
} from "@/types"

const POLL_INTERVAL_MS = 400
const AMPLITUDE_TOOL = "amplitude-change"

interface ReportViewProps {
  sceneId: string | null
  onClose: () => void
}

/**
 * The Report tool. It renders two siblings for the page's flex row: the
 * document in the center, and the queue or contents on the right.
 */
export function ReportView({ sceneId, onClose }: ReportViewProps) {
  const [question, setQuestion] = useState("")
  const [plan, setPlan] = useState<ReportPlan | null>(null)
  const [planning, setPlanning] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [reportError, setReportError] = useState<string | null>(null)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [watching, setWatching] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [scenePartners, setScenePartners] = useState<string[]>([])
  const [partnersError, setPartnersError] = useState<string | null>(null)
  const [partnerChoice, setPartnerChoice] = useState<string | null>(null)

  const running = job?.status === "running"

  // Load what is already saved, and pick up a job that is already running.
  useEffect(() => {
    if (!sceneId) {
      return undefined
    }

    let active = true

    void Promise.all([fetchReport(sceneId), fetchCurrentJob()])
      .then(([saved, current]) => {
        if (!active) {
          return
        }

        setReport(saved)
        setReportError(null)
        setJob(current)
        // A saved question is the one the document answers.
        setQuestion((existing) => existing || saved.question)
      })
      .catch((error: unknown) => {
        if (active) {
          setReportError(messageFrom(error, "Could not read the saved report."))
        }
      })

    return () => {
      active = false
    }
  }, [sceneId])

  // The scene's own tool list names the partners amplitude change can use.
  useEffect(() => {
    if (!sceneId) {
      return undefined
    }

    let active = true

    void fetchAnalysisTools(sceneId)
      .then((response) => {
        if (active) {
          setScenePartners(partnersOf(response.tools))
          setPartnersError(null)
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setScenePartners([])
          setPartnersError(
            messageFrom(error, "Could not read the partner scenes.")
          )
        }
      })

    return () => {
      active = false
    }
  }, [sceneId])

  // While the job runs, every tick reads the sentence and then the report, so
  // a finished section appears before the job ends. The job is read first, so
  // the report is never older than the sentence beside it.
  useEffect(() => {
    if (!sceneId || !running) {
      return undefined
    }

    let active = true
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const nextJob = await fetchCurrentJob()
          const nextReport = await fetchReport(sceneId)

          if (!active) {
            return
          }

          setReport(nextReport)
          setReportError(null)
          setJob(nextJob)
        } catch (error) {
          if (active) {
            setJob((current) =>
              current
                ? {
                    ...current,
                    status: "failed",
                    error: messageFrom(error, "Lost the report job."),
                  }
                : current
            )
          }
        }
      })()
    }, POLL_INTERVAL_MS)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [sceneId, running, job])

  // Read the job once after a start, so the poll above takes over.
  const watchJob = useCallback(async () => {
    setWatching(true)

    try {
      setJob(await fetchCurrentJob())
    } catch (error) {
      setRunError(messageFrom(error, "Could not read the report job."))
    }
  }, [])

  async function makePlan() {
    if (!sceneId || !question.trim()) {
      return
    }

    setPlanning(true)
    setPlanError(null)
    setPlan(null)

    try {
      const next = await planReport(sceneId, question)
      // Fail fast on a plan that is not the server's shape.
      splitPlan(next)
      setPlan(next)
    } catch (error) {
      // A 409 carries the sentence to show: Set OPENAI_API_KEY to ask a question.
      setPlanError(messageFrom(error, "Could not plan the report."))
    } finally {
      setPlanning(false)
    }
  }

  async function compile() {
    if (!sceneId || !plan) {
      return
    }

    setRunError(null)

    try {
      await startReportRun(sceneId, question, runnableIds(plan))
    } catch (error) {
      setRunError(messageFrom(error, "Could not start the report."))

      // A job already running is still worth watching. Any other failure is not.
      if (!(error instanceof MeasureJobConflictError)) {
        return
      }
    }

    await watchJob()
  }

  async function runComparison(partnerId: string) {
    if (!sceneId) {
      return
    }

    setRunError(null)

    try {
      await startReportAmplitude(sceneId, partnerId)
    } catch (error) {
      setRunError(messageFrom(error, "Could not start the comparison."))

      if (!(error instanceof MeasureJobConflictError)) {
        return
      }
    }

    await watchJob()
  }

  if (!sceneId) {
    return (
      <div className="flex min-w-0 flex-1 items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">
          Open a scene from the library before writing a report.
        </p>
      </div>
    )
  }

  const split = plan ? splitPlan(plan) : null
  const options = partnerOptions(plan, scenePartners)
  const partnerId =
    partnerChoice && options.includes(partnerChoice)
      ? partnerChoice
      : (options[0] ?? "")
  const failed = report ? failedSections(report) : []
  const sections = report?.sections ?? []

  return (
    <>
      <div className="flex min-h-[40vh] min-w-0 flex-1 flex-col md:min-h-0">
        <ScrollArea className="flex-1">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                void makePlan()
              }}
            >
              <label className="flex flex-col gap-1 text-sm font-medium">
                Note
                <textarea
                  className="min-h-20 rounded-md border bg-background px-2 py-1.5 text-sm font-normal"
                  value={question}
                  placeholder="What do you want to know about this scene?"
                  disabled={running}
                  onChange={(event) => {
                    setQuestion(event.target.value)
                    // A new note makes the earlier plan stale.
                    setPlan(null)
                    setPlanError(null)
                  }}
                />
              </label>
              <div className="flex items-center gap-2">
                <Button
                  type="submit"
                  variant="outline"
                  disabled={planning || running || !question.trim()}
                >
                  {planning ? "Planning" : "Plan"}
                </Button>
                {plan && split ? (
                  <Button
                    type="button"
                    disabled={
                      running ||
                      split.selected.length + split.waiting.length === 0
                    }
                    onClick={() => {
                      void compile()
                    }}
                  >
                    Compile
                  </Button>
                ) : null}
              </div>
              {planError ? (
                <p role="alert" className="text-sm text-destructive">
                  {planError}
                </p>
              ) : null}
              {runError ? (
                <p role="alert" className="text-sm text-destructive">
                  {runError}
                </p>
              ) : null}
            </form>

            {plan && split ? <PlanSummary split={split} plan={plan} /> : null}

            {partnersError ? (
              <p role="alert" className="text-sm text-destructive">
                {partnersError}
              </p>
            ) : null}

            {reportError ? (
              <p role="alert" className="text-sm text-destructive">
                {reportError}
              </p>
            ) : null}

            {sections.length === 0 && !reportError ? (
              <p className="text-sm text-muted-foreground">
                No report for this scene yet. Write a note, plan it, then
                compile.
              </p>
            ) : null}

            {sections.map((section) => (
              <SectionCard
                key={section.tool_id}
                section={section}
                partnerOptions={options}
                partnerId={partnerId}
                busy={running}
                onPartner={setPartnerChoice}
                onRunComparison={(id) => {
                  void runComparison(id)
                }}
              />
            ))}
          </div>
        </ScrollArea>
      </div>

      <section
        aria-label={running ? "Report queue" : "Report contents"}
        className="flex max-h-[50vh] min-h-0 flex-col border-t md:max-h-none md:w-96 md:border-t-0 md:border-l"
      >
        <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
          <h2 className="text-sm font-medium">
            {running ? "Queue" : "Contents"}
          </h2>
          <Button type="button" variant="ghost" size="xs" onClick={onClose}>
            Close
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-3 p-3">
            {job && (running || watching) ? (
              <JobLine job={job} failedCount={failed.length} />
            ) : null}
            <ul className="flex flex-col gap-1 text-sm">
              {queueRows(plan, sections).map((row) => (
                <li key={row.toolId}>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-full justify-between"
                    disabled={!row.section}
                    onClick={() => {
                      document
                        .getElementById(sectionAnchor(row.toolId))
                        ?.scrollIntoView({ block: "start" })
                    }}
                  >
                    <span className="truncate">{toolLabel(row.toolId)}</span>
                    <span className="text-xs text-muted-foreground">
                      {row.status}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
            {sections.length > 0 ? (
              <a
                className={buttonVariants({ variant: "outline" })}
                href={reportPdfUrl(sceneId)}
                download
              >
                Download PDF
              </a>
            ) : null}
          </div>
        </ScrollArea>
      </section>
    </>
  )
}

/** The checked plan: what runs, what waits, and what the belt keeps locked. */
function PlanSummary({
  split,
  plan,
}: {
  split: ReturnType<typeof splitPlan>
  plan: ReportPlan
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3 text-sm">
      <h3 className="font-medium">Plan</h3>
      <p>
        <span className="text-muted-foreground">Runs: </span>
        {split.selected.length > 0
          ? split.selected.map(toolLabel).join(", ")
          : "nothing"}
      </p>
      {split.waiting.length > 0 ? (
        <p>
          <span className="text-muted-foreground">Waits for a choice: </span>
          {split.waiting.map(toolLabel).join(", ")}
          {plan.partner_id
            ? `. Suggested second scene: ${plan.partner_id}`
            : ""}
        </p>
      ) : null}
      {split.locked.length > 0 ? (
        <div>
          <p className="text-muted-foreground">Locked, not run:</p>
          <ul className="flex flex-col gap-1">
            {split.locked.map((tool) => (
              <li key={tool.id}>
                <span className="font-medium">{toolLabel(tool.id)}</span>
                {tool.reason ? `. ${tool.reason}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

interface SectionCardProps {
  section: ReportSection
  partnerOptions: string[]
  partnerId: string
  busy: boolean
  onPartner: (partnerId: string) => void
  onRunComparison: (partnerId: string) => void
}

/** One tool's part of the document. */
function SectionCard({
  section,
  partnerOptions: options,
  partnerId,
  busy,
  onPartner,
  onRunComparison,
}: SectionCardProps) {
  const locked = section.status === "locked"
  const waitsForPartner =
    section.status === "waiting" && section.tool_id === AMPLITUDE_TOOL
  const belt = beltText(section)
  const summary = summaryFromMeasurement(section.measurement)

  return (
    <article
      id={sectionAnchor(section.tool_id)}
      className="flex flex-col gap-2 rounded-md border p-3"
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{toolLabel(section.tool_id)}</h3>
        <span className="text-xs text-muted-foreground">{section.status}</span>
      </header>

      {section.status === "running" ? (
        <p className="text-sm text-muted-foreground">Running.</p>
      ) : null}

      {/* A locked section is the belt's reason and never a picture. */}
      {!locked && section.overview_url ? (
        <img
          className="w-full rounded-md border"
          src={section.overview_url}
          alt={`${toolLabel(section.tool_id)} picture with its legend`}
          loading="lazy"
        />
      ) : null}

      <Briefing
        text={section.briefing_md}
        failed={section.status === "failed"}
      />

      {summary.length > 0 && section.status === "done" ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {summary.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {belt !== null && section.status === "done" ? (
        <p className="text-xs text-muted-foreground">
          The belt&apos;s own text. It keeps the limit as written.
        </p>
      ) : null}

      {waitsForPartner ? (
        <div className="flex flex-col gap-2">
          {options.length > 0 ? (
            <label className="flex flex-col gap-1 text-sm">
              Second scene
              <select
                className="rounded-md border bg-background px-2 py-1.5 text-sm"
                value={partnerId}
                disabled={busy}
                onChange={(event) => {
                  onPartner(event.target.value)
                }}
              >
                {options.map((partner) => (
                  <option key={partner} value={partner}>
                    {partner}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="text-sm text-muted-foreground">
              No second scene on disk can be compared with this one.
            </p>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={busy || !partnerId}
            onClick={() => {
              onRunComparison(partnerId)
            }}
          >
            Run this comparison
          </Button>
        </div>
      ) : null}
    </article>
  )
}

/** A stored briefing as headings, paragraphs, and bullets. Never HTML. */
function Briefing({ text, failed }: { text: string; failed: boolean }) {
  const blocks = briefingBlocks(text)
  const tone = failed ? "text-destructive" : "text-muted-foreground"

  return (
    <div className={`flex flex-col gap-2 text-sm leading-6 ${tone}`}>
      {blocks.map((block, index) => {
        if (block.kind === "heading") {
          return (
            <h4 key={index} className="font-medium text-foreground">
              {block.text}
            </h4>
          )
        }

        if (block.kind === "list") {
          return (
            <ul key={index} className="list-disc pl-5">
              {block.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )
        }

        return <p key={index}>{block.text}</p>
      })}
    </div>
  )
}

/** The job sentence, and the sections that failed once the job has ended. */
function JobLine({
  job,
  failedCount,
}: {
  job: JobSnapshot
  failedCount: number
}) {
  if (job.status === "running") {
    return (
      <p className="text-sm" aria-live="polite">
        {job.sentence}
        {job.step_count > 0 ? ` (${job.step_index} of ${job.step_count})` : ""}
      </p>
    )
  }

  if (job.status === "failed") {
    return (
      <p role="alert" className="text-sm text-destructive">
        {job.error ?? "The report job failed."}
      </p>
    )
  }

  // A done job only means the run ended. Failed sections are said out loud.
  return (
    <p className="text-sm">
      {failedCount > 0
        ? `The job ended. ${failedCount} ${failedCount === 1 ? "section" : "sections"} failed.`
        : "The job ended."}
    </p>
  )
}

interface QueueRow {
  toolId: string
  status: string
  section: ReportSection | null
}

/**
 * The rows of the right pane: every saved section, then planned tools that
 * have no section yet, which are still queued.
 */
function queueRows(
  plan: ReportPlan | null,
  sections: ReportSection[]
): QueueRow[] {
  const rows: QueueRow[] = sections.map((section) => ({
    toolId: section.tool_id,
    status: section.status,
    section,
  }))

  if (!plan) {
    return rows
  }

  const known = new Set(rows.map((row) => row.toolId))

  for (const toolId of splitPlan(plan).selected) {
    if (!known.has(toolId)) {
      rows.push({ toolId, status: "queued", section: null })
    }
  }

  return rows
}

function partnersOf(tools: AnalysisTool[]): string[] {
  return tools.find((tool) => tool.id === AMPLITUDE_TOOL)?.partners ?? []
}

function sectionAnchor(toolId: string): string {
  return `report-section-${toolId}`
}

function messageFrom(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message || fallback
  }

  return fallback
}
