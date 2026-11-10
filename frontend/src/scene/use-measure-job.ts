import { useCallback, useEffect, useRef, useState } from "react"

import {
  ApiError,
  fetchCurrentJob,
  startMeasureJob,
} from "@/api"
import type { JobResult, JobSnapshot } from "@/types"

const POLL_INTERVAL_MS = 400

interface MeasureJobState {
  snapshot: JobSnapshot | null
  isStarting: boolean
  startError: string | null
  isRunning: boolean
  start: () => Promise<void>
}

/**
 * One measurement at a time. Poll only while a job started in this view is
 * running, and publish results when that job reaches done.
 */
export function useMeasureJob(
  onDone: (result: JobResult) => void
): MeasureJobState {
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
    let active = true
    const id = requestId.current + 1
    requestId.current = id

    void fetchCurrentJob()
      .then((next) => {
        if (!active || id !== requestId.current) {
          return
        }

        publish(next)
      })
      .catch((error: unknown) => {
        if (!active || id !== requestId.current) {
          return
        }

        setStartError(messageFrom(error))
      })

    return () => {
      active = false
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

  const start = useCallback(async () => {
    setIsStarting(true)
    setStartError(null)

    try {
      await startMeasureJob()
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
  }, [load])

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

  return "Could not run the measurement job."
}
