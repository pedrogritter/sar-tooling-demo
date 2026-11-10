import { useCallback, useEffect, useRef, useState } from "react"

import { ApiError, fetchCurrentJob, startAnalysisJob } from "@/api"
import type { JobResult, JobSnapshot } from "@/types"

const POLL_INTERVAL_MS = 400

interface AnalysisJobState {
  snapshot: JobSnapshot | null
  isStarting: boolean
  startError: string | null
  isRunning: boolean
  start: (
    sceneId: string,
    toolId: string,
    partnerId: string | null
  ) => Promise<void>
}

/** Poll the one analysis job and publish its picture when it finishes. */
export function useAnalysisJob(
  onDone: (result: JobResult) => void
): AnalysisJobState {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const onDoneRef = useRef(onDone)
  const requestId = useRef(0)
  const sawRunning = useRef(false)

  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  const publish = useCallback((next: JobSnapshot) => {
    setSnapshot(next)

    if (next.status === "running") {
      sawRunning.current = true
    }

    if (next.status === "done" && next.result && sawRunning.current) {
      sawRunning.current = false
      onDoneRef.current(next.result)
    }
  }, [])

  const load = useCallback(async () => {
    const id = requestId.current + 1
    requestId.current = id

    try {
      const next = await fetchCurrentJob()
      if (id !== requestId.current) {
        return
      }

      publish(next)
      setStartError(null)
    } catch (error) {
      if (id !== requestId.current) {
        return
      }

      setStartError(messageFrom(error))
    }
  }, [publish])

  useEffect(() => {
    if (snapshot?.status !== "running") {
      return undefined
    }

    const timer = window.setTimeout(() => {
      void load()
    }, POLL_INTERVAL_MS)

    return () => {
      window.clearTimeout(timer)
    }
  }, [load, snapshot])

  const start = useCallback(
    async (sceneId: string, toolId: string, partnerId: string | null) => {
      setIsStarting(true)
      setStartError(null)

      try {
        await startAnalysisJob(sceneId, toolId, partnerId)
        sawRunning.current = true
        await load()
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          await load()
          return
        }

        setStartError(messageFrom(error))
      } finally {
        setIsStarting(false)
      }
    },
    [load]
  )

  return {
    snapshot,
    isStarting,
    startError,
    isRunning: snapshot?.status === "running" || isStarting,
    start,
  }
}

function messageFrom(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message
  }

  return "Could not run the analysis."
}
