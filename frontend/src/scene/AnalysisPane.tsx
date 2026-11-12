import { useEffect, useRef, useState } from "react"

import { MeasureCard } from "@/scene/MeasureCard"
import { savedToolResult, summaryFromMeasurement } from "@/scene/placeholder"
import { analysisRunDisabled } from "@/scene/stage"
import { useAnalysisJob } from "@/scene/use-analysis-job"
import type { AnalysisTool, JobResult } from "@/types"

interface AnalysisPaneProps {
  sceneId: string | null
  toolId: string
  description: string
  tools: AnalysisTool[]
  toolsError: string | null
  onResult: (result: JobResult) => void
}

/** One analysis tool: the lock sentence, an optional pair, and the job. */
export function AnalysisPane({
  sceneId,
  toolId,
  description,
  tools,
  toolsError,
  onResult,
}: AnalysisPaneProps) {
  const [partnerChoice, setPartnerChoice] = useState<string | null>(null)
  const [loadedScene, setLoadedScene] = useState(sceneId)
  const job = useAnalysisJob(onResult)
  const tool = tools.find((item) => item.id === toolId) ?? null
  const partnerId =
    partnerChoice && tool?.partners.includes(partnerChoice)
      ? partnerChoice
      : (tool?.partners[0] ?? "")
  const onResultRef = useRef(onResult)

  if (sceneId !== loadedScene) {
    setLoadedScene(sceneId)
    setPartnerChoice(null)
  }

  useEffect(() => {
    onResultRef.current = onResult
  }, [onResult])

  useEffect(() => {
    const status = job.snapshot?.status
    if (status === "running" || status === "done") {
      return
    }

    const saved = savedToolResult(tool)
    if (!saved.overview_url && !saved.measurement && !saved.briefing_html) {
      return
    }

    onResultRef.current(saved)
  }, [job.snapshot?.status, tool])

  if (!sceneId) {
    return (
      <p className="p-3 text-sm text-muted-foreground">
        Open a scene from the library before running a tool.
      </p>
    )
  }

  const locked = tool?.locked ?? true
  const reason = tool?.reason || toolsError
  const running = job.isRunning || job.snapshot?.status === "running"
  const shown = running
    ? null
    : job.snapshot?.status === "done" && job.snapshot.result
      ? job.snapshot.result
      : savedToolResult(tool)
  const summary = summaryFromMeasurement(shown?.measurement ?? null)

  return (
    <div className="flex flex-col gap-3 p-3">
      <p className="text-sm text-muted-foreground">{description}</p>
      {reason ? <p className="text-sm">{reason}</p> : null}
      {tool?.needs_partner && !locked ? (
        <label className="flex flex-col gap-1 text-sm">
          Second scene
          <select
            className="rounded-md border bg-background px-2 py-1.5 text-sm"
            value={partnerId}
            onChange={(event) => {
              setPartnerChoice(event.target.value)
            }}
          >
            {tool.partners.map((partner) => (
              <option key={partner} value={partner}>
                {partner}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {tool && !tool.needs_partner && tool.partners.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Uses this scene and {tool.partners.length} matched{" "}
          {tool.partners.length === 1 ? "scene" : "scenes"}.
        </p>
      ) : null}
      <MeasureCard
        snapshot={job.snapshot}
        isRunning={job.isRunning}
        startError={job.startError}
        showHeading={false}
        disabled={analysisRunDisabled(tool)}
        actionLabel="Run tool"
        runningLabel="Running"
        onMeasure={() => {
          if (!sceneId || analysisRunDisabled(tool)) {
            return
          }

          void job.start(
            sceneId,
            toolId,
            tool?.needs_partner ? partnerId : null
          )
        }}
      />
      {summary.length > 0 ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {summary.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {shown?.briefing_html ? (
        <div
          className="text-sm leading-6 text-muted-foreground"
          dangerouslySetInnerHTML={{
            __html: shown.briefing_html,
          }}
        />
      ) : null}
    </div>
  )
}
