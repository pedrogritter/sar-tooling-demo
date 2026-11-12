import { useCallback, useEffect, useState } from "react"

import {
  ApiError,
  MeasureJobConflictError,
  fetchAnalysisTools,
  fetchCurrentJob,
  fetchModelKey,
  fetchReport,
  isReportKeyRequiredError,
  reportPdfUrl,
  saveModelKey,
  startReportRun,
} from "@/api"
import { Button, buttonVariants } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import {
  type BriefingBlock,
  type FigureView,
  type HeldView,
  type RailStep,
  briefingBlocks,
  eligiblePartners,
  figureViews,
  heldViews,
  normalizeReport,
  progressPercent,
  reportHasDocument,
  reportIsComplete,
  reportPartnerId,
  reportProgress,
  reportRail,
  shouldLoadReport,
  synthesisText,
} from "@/scene/report"
import type { JobSnapshot, ModelKeySource, Report } from "@/types"

const POLL_INTERVAL_MS = 400

interface ReportViewProps {
  sceneId: string | null
  onClose: () => void
}

/**
 * The Report tool. The document sits in the center and the step rail on the
 * right. Start runs the whole report. Narrator lines stay on the active rail
 * row and are not copied into the document.
 */
export function ReportView({ sceneId, onClose }: ReportViewProps) {
  const [keySource, setKeySource] = useState<ModelKeySource | "loading">(
    "loading"
  )
  const [keyDraft, setKeyDraft] = useState("")
  const [savingKey, setSavingKey] = useState(false)
  const [keyError, setKeyError] = useState<string | null>(null)
  const [replacingKey, setReplacingKey] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [reportError, setReportError] = useState<string | null>(null)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [scenePartners, setScenePartners] = useState<string[]>([])
  const [partnersReady, setPartnersReady] = useState(false)
  const [partnersError, setPartnersError] = useState<string | null>(null)
  const [partnerChoice, setPartnerChoice] = useState("")

  const running = job?.status === "running"
  const keyReady = keySource === "environment" || keySource === "session"
  const askingForKey = keySource === "unset" || replacingKey
  const startDisabled = !keyReady || replacingKey || starting || running

  // The page has to know whether a key is set before Start can run.
  useEffect(() => {
    let active = true

    void fetchModelKey()
      .then((status) => {
        if (active) {
          setKeySource(status.source)
          setKeyError(null)
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setKeySource("unset")
          setKeyError(messageFrom(error, "Could not check the OpenAI key."))
        }
      })

    return () => {
      active = false
    }
  }, [])

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

        setReport(normalizeReport(saved))
        setReportError(null)
        setJob(current)
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

  // Eligible partners are the amplitude-change list. An empty list hides the picker.
  useEffect(() => {
    if (!sceneId) {
      return undefined
    }

    let active = true

    void fetchAnalysisTools(sceneId)
      .then((response) => {
        if (active) {
          setScenePartners(eligiblePartners(response.tools))
          setPartnersReady(true)
          setPartnersError(null)
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setScenePartners([])
          setPartnersReady(false)
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

          setReport(normalizeReport(nextReport))
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

  // After every start, read the job and then the report. A job that is
  // already done or failed on this first read never reaches the poll above,
  // so its new sections are loaded here. A running job is picked up by the poll.
  const watchJob = useCallback(async (id: string) => {
    let current: JobSnapshot

    try {
      current = await fetchCurrentJob()
      setJob(current)
    } catch (error) {
      setRunError(messageFrom(error, "Could not read the report job."))
      return
    }

    if (!shouldLoadReport(current.status)) {
      return
    }

    try {
      setReport(normalizeReport(await fetchReport(id)))
      setReportError(null)
    } catch (error) {
      setReportError(messageFrom(error, "Could not read the saved report."))
    }
  }, [])

  async function saveKey() {
    const apiKey = keyDraft.trim()

    if (!apiKey) {
      return
    }

    setSavingKey(true)
    setKeyError(null)

    try {
      const status = await saveModelKey(apiKey)
      setKeySource(status.source)
      setKeyDraft("")
      setReplacingKey(false)
    } catch (error) {
      setKeyError(messageFrom(error, "Could not save the OpenAI key."))
    } finally {
      setSavingKey(false)
    }
  }

  async function start() {
    if (!sceneId || startDisabled) {
      return
    }

    const partnerId = reportPartnerId(
      scenePartners.includes(partnerChoice) ? partnerChoice : ""
    )

    setStarting(true)
    setRunError(null)

    try {
      await startReportRun(sceneId, partnerId)
    } catch (error) {
      if (isReportKeyRequiredError(error)) {
        const message = messageFrom(error, "Could not start the report.")
        setKeySource("unset")
        setKeyError(message)
        setStarting(false)
        return
      }

      setRunError(messageFrom(error, "Could not start the report."))

      // A job already running is still worth watching. Any other failure is not.
      if (!(error instanceof MeasureJobConflictError)) {
        setStarting(false)
        return
      }
    }

    try {
      await watchJob(sceneId)
    } finally {
      setStarting(false)
    }
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

  const selectedPartner = scenePartners.includes(partnerChoice)
    ? partnerChoice
    : ""
  const synthesis = synthesisText(report)
  const figures = report ? figureViews(report) : []
  const held = report ? heldViews(report) : []
  const steps = reportRail(report, running, job?.sentence ?? "")
  // A running job whose file is still the previous finished report has not
  // published a new order yet, so the bar waits for that file.
  const progress = reportProgress(
    running && report?.phase !== "done" ? report : null
  )
  const showDocument = reportHasDocument(report)
  const complete = reportIsComplete(report) && !running
  const showPartners = partnersReady && scenePartners.length > 0

  return (
    <>
      <div className="flex min-h-[40vh] min-w-0 flex-1 flex-col md:min-h-0">
        <ScrollArea className="flex-1">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
            <header className="flex flex-col gap-2">
              <h2 className="text-base font-medium">Scene report</h2>
              <p className="text-sm leading-6 text-muted-foreground">
                Start runs the measurements this scene can support, then writes
                one reading of the numbers. You can read it here or download it.
              </p>
              <p className="text-sm leading-6 text-muted-foreground">
                A bright return stays a bright radar return. The report does not
                name a ship, a spill, a tide height, or a building height.
              </p>
              <p className="text-sm leading-6 text-muted-foreground">
                A scene that is only in the catalogue is not downloaded.
              </p>
            </header>

            {keySource === "loading" && !keyError ? (
              <p className="text-sm text-muted-foreground">
                Checking whether an OpenAI key is set.
              </p>
            ) : null}

            {keySource === "environment" ? (
              <p className="text-sm text-muted-foreground">
                An OpenAI key is set for this server, so the report can order
                the measurements, narrate each step, and write the reading.
              </p>
            ) : null}

            {askingForKey ? (
              <KeyForm
                draft={keyDraft}
                saving={savingKey}
                error={keyError}
                replacing={replacingKey}
                onDraft={setKeyDraft}
                onCancel={() => {
                  setReplacingKey(false)
                  setKeyDraft("")
                  setKeyError(null)
                }}
                onSubmit={() => {
                  void saveKey()
                }}
              />
            ) : null}

            {keyError && !askingForKey ? (
              <p role="alert" className="text-sm text-destructive">
                {keyError}
              </p>
            ) : null}

            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                void start()
              }}
            >
              {showPartners ? (
                <label className="flex flex-col gap-1 text-sm font-medium">
                  Second scene
                  <select
                    className="rounded-md border bg-background px-2 py-1.5 text-sm font-normal"
                    value={selectedPartner}
                    disabled={starting || running}
                    onChange={(event) => {
                      setPartnerChoice(event.target.value)
                    }}
                  >
                    <option value="">This scene only</option>
                    {scenePartners.map((partner) => (
                      <option key={partner} value={partner}>
                        {partner}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {showPartners ? (
                <p className="text-sm text-muted-foreground">
                  {selectedPartner
                    ? "Amplitude change uses this second scene. Stack measurements still use every matched date, not only this one."
                    : "This scene only runs the measurements that stand on their own. A second scene adds amplitude change and the stack measurements. A stack uses every matched date."}
                </p>
              ) : null}
              {keySource === "session" && !replacingKey ? (
                <p className="text-sm text-muted-foreground">
                  A key entered on this page is set for this server.{" "}
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto px-0"
                    onClick={() => {
                      setReplacingKey(true)
                    }}
                  >
                    Use a different key
                  </Button>
                </p>
              ) : null}
              {complete ? (
                <p className="text-sm text-muted-foreground">
                  A report is already saved below. Start again replaces it.
                </p>
              ) : null}
              <div>
                <Button type="submit" disabled={startDisabled}>
                  Start
                </Button>
              </div>
              {runError ? (
                <p role="alert" className="text-sm text-destructive">
                  {runError}
                </p>
              ) : null}
            </form>

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

            {!showDocument && !reportError && !running ? (
              <p className="text-sm text-muted-foreground">
                No report for this scene yet.
              </p>
            ) : null}

            {synthesis ? (
              <div className="flex flex-col gap-2 text-sm leading-6">
                <Briefing text={synthesis} failed={false} />
              </div>
            ) : null}

            {figures.map((figure) => (
              <FigureCard key={figure.toolId} figure={figure} />
            ))}

            {held.map((item) => (
              <HeldCard key={item.toolId} item={item} />
            ))}
          </div>
        </ScrollArea>
      </div>

      <section
        aria-label="This report"
        aria-busy={running}
        className="flex max-h-[50vh] min-h-0 flex-col border-t md:max-h-none md:w-96 md:border-t-0 md:border-l"
      >
        <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
          <h2 className="text-sm font-medium">This report</h2>
          <Button type="button" variant="ghost" size="xs" onClick={onClose}>
            Close
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-3 p-3">
            {running && progress.total > 0 ? (
              <Progress
                value={progressPercent(progress.completed, progress.total)}
                className="flex-col gap-2"
              >
                <span className="text-xs text-muted-foreground tabular-nums">
                  {progress.completed} of {progress.total}
                </span>
              </Progress>
            ) : null}
            {job?.status === "failed" ? (
              <p role="alert" className="text-sm text-destructive">
                {job.error ?? "The report job failed."}
              </p>
            ) : null}
            {steps.length > 0 ? (
              <ol className="flex flex-col gap-2 text-sm">
                {steps.map((step) => (
                  <RailRow key={step.key} step={step} />
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">
                The steps appear here after you start.
              </p>
            )}
            {complete ? (
              <div className="flex flex-col gap-1">
                <a
                  className={buttonVariants({ variant: "outline" })}
                  href={reportPdfUrl(sceneId)}
                  download
                >
                  Download PDF
                </a>
                <p className="text-xs text-muted-foreground">
                  The report saved for this scene.
                </p>
              </div>
            ) : null}
          </div>
        </ScrollArea>
      </section>
    </>
  )
}

/** The key field shown when this server has no key, or when a page key is replaced. */
function KeyForm({
  draft,
  saving,
  error,
  replacing,
  onDraft,
  onCancel,
  onSubmit,
}: {
  draft: string
  saving: boolean
  error: string | null
  replacing: boolean
  onDraft: (value: string) => void
  onCancel: () => void
  onSubmit: () => void
}) {
  return (
    <form
      className="flex flex-col gap-2 rounded-md border p-3"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <p className="text-sm leading-6 text-muted-foreground">
        Starting a report needs an OpenAI API key. The key is how the app orders
        the measurements, narrates each step, and writes the reading. The
        measurements themselves stay on this machine. A key saved here stays in
        this running server only. It is not written into the project or the
        image. Restarting the container clears it. You can also put
        OPENAI_API_KEY in a .env file next to docker-compose.yml, or export it
        in the shell, and start the container again.
      </p>
      <label className="flex flex-col gap-1 text-sm font-medium">
        OpenAI API key
        <input
          className="rounded-md border bg-background px-2 py-1.5 text-sm font-normal"
          type="password"
          name="openai-api-key"
          autoComplete="off"
          value={draft}
          disabled={saving}
          onChange={(event) => {
            onDraft(event.target.value)
          }}
        />
      </label>
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={saving || !draft.trim()}>
          {saving ? "Saving key" : "Save key"}
        </Button>
        {replacing ? (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  )
}

/** One finished measurement: the picture, the summary rows, and the limit. */
function FigureCard({ figure }: { figure: FigureView }) {
  return (
    <article
      id={sectionAnchor(figure.toolId)}
      className="flex flex-col gap-2 rounded-md border p-3"
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{figure.label}</h3>
        <span className="text-xs text-muted-foreground">{figure.status}</span>
      </header>
      {figure.partnerId ? (
        <p className="text-sm text-muted-foreground">
          Compared with {figure.partnerId}.
        </p>
      ) : null}
      {figure.imageUrl ? (
        <img
          className="w-full rounded-md border"
          src={figure.imageUrl}
          alt={`${figure.label} picture with its legend`}
          loading="lazy"
        />
      ) : null}
      {figure.summary.length > 0 ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {figure.summary.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {figure.limit ? (
        <p className="text-xs text-muted-foreground">{figure.limit}</p>
      ) : null}
    </article>
  )
}

/** A tool that could not run, or that failed, after the figures. */
function HeldCard({ item }: { item: HeldView }) {
  return (
    <article
      id={sectionAnchor(item.toolId)}
      className="flex flex-col gap-2 rounded-md border p-3"
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{item.label}</h3>
        <span className="text-xs text-muted-foreground">{item.status}</span>
      </header>
      {item.text.trim() ? (
        <Briefing text={item.text} failed={item.status === "Failed"} />
      ) : null}
    </article>
  )
}

/** One rail step. The narrator line is rendered only when this row is active. */
function RailRow({ step }: { step: RailStep }) {
  return (
    <li
      className="flex flex-col gap-1"
      aria-current={step.active ? "step" : undefined}
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn(
          "h-auto w-full justify-between py-1",
          step.active && "bg-muted"
        )}
        onClick={() => {
          if (!step.toolId) {
            return
          }

          document
            .getElementById(sectionAnchor(step.toolId))
            ?.scrollIntoView({ block: "start" })
        }}
      >
        <span className="truncate">{step.label}</span>
        {step.status ? (
          <span className="shrink-0 text-xs text-muted-foreground">
            {step.status}
          </span>
        ) : null}
      </Button>
      {step.note ? (
        <p
          className="px-2 text-xs leading-5 text-muted-foreground"
          aria-live="polite"
        >
          {step.note}
        </p>
      ) : null}
    </li>
  )
}

/** A stored briefing as headings, paragraphs, and bullets. Never HTML. */
function Briefing({ text, failed }: { text: string; failed: boolean }) {
  const blocks = briefingBlocks(text)
  const tone = failed ? "text-destructive" : "text-muted-foreground"

  return (
    <div className={cn("flex flex-col gap-2 text-sm leading-6", tone)}>
      {blocks.map((block, index) => (
        <BriefingBlockView key={index} block={block} />
      ))}
    </div>
  )
}

function BriefingBlockView({ block }: { block: BriefingBlock }) {
  if (block.kind === "heading") {
    return <h4 className="font-medium text-foreground">{block.text}</h4>
  }

  if (block.kind === "list") {
    return (
      <ul className="list-disc pl-5">
        {block.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    )
  }

  return <p>{block.text}</p>
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
