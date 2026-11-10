import { useEffect, useRef, useState } from "react"

import { fetchAnalysisTools } from "@/api"
import { MeasureCard } from "@/scene/MeasureCard"
import { useAnalysisJob } from "@/scene/use-analysis-job"
import type { AnalysisTool, JobResult } from "@/types"

interface AnalysisPaneProps {
  sceneId: string | null
  toolId: string
  description: string
  onResult: (result: JobResult) => void
}

/** One analysis tool: the lock sentence, an optional pair, and the job. */
export function AnalysisPane({
  sceneId,
  toolId,
  description,
  onResult,
}: AnalysisPaneProps) {
  const [tools, setTools] = useState<AnalysisTool[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [partnerChoice, setPartnerChoice] = useState<string | null>(null)
  const [loadedScene, setLoadedScene] = useState(sceneId)
  const job = useAnalysisJob(onResult)
  const visibleTools = sceneId === loadedScene ? tools : []
  const tool = visibleTools.find((item) => item.id === toolId) ?? null
  const partnerId =
    partnerChoice && tool?.partners.includes(partnerChoice)
      ? partnerChoice
      : (tool?.partners[0] ?? "")
  const onResultRef = useRef(onResult)

  if (sceneId !== loadedScene) {
    setLoadedScene(sceneId)
    setTools([])
    setLoadError(null)
    setPartnerChoice(null)
  }

  useEffect(() => {
    if (!sceneId) {
      return undefined
    }

    let active = true
    void fetchAnalysisTools(sceneId)
      .then((response) => {
        if (!active) {
          return
        }

        setTools(response.tools)
        setLoadError(null)
      })
      .catch((error: unknown) => {
        if (!active) {
          return
        }

        setLoadError(messageFrom(error))
      })

    return () => {
      active = false
    }
  }, [sceneId])

  useEffect(() => {
    onResultRef.current = onResult
  }, [onResult])

  useEffect(() => {
    if (!tool?.overview_url || job.snapshot?.status === "running") {
      return
    }

    onResultRef.current({
      measurement: null,
      briefing_html: null,
      overview_url: tool.overview_url,
    })
  }, [job.snapshot?.status, tool])

  if (!sceneId) {
    return (
      <p className="p-3 text-sm text-muted-foreground">
        Open a scene from the library before running a tool.
      </p>
    )
  }

  const locked = tool?.locked ?? true
  const reason = tool?.reason || loadError
  const summary = summaryRows(job.snapshot?.result?.measurement ?? null)

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
        disabled={locked || !tool}
        actionLabel="Run tool"
        runningLabel="Running"
        onMeasure={() => {
          if (!sceneId || locked) {
            return
          }

          void job.start(sceneId, toolId, tool?.needs_partner ? partnerId : null)
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
      {job.snapshot?.result?.briefing_html ? (
        <div
          className="text-sm leading-6 text-muted-foreground"
          dangerouslySetInnerHTML={{
            __html: job.snapshot.result.briefing_html,
          }}
        />
      ) : null}
    </div>
  )
}

function summaryRows(
  measurement: JobResult["measurement"]
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

function messageFrom(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message
  }

  return "Could not read which tools this scene can run."
}
