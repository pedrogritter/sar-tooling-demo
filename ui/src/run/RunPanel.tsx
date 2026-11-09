import { useCallback, useEffect, useRef, useState } from "react";

import type { JobSnapshot, RunPanelProps } from "@/types";

import "./run.css";

const POLL_INTERVAL_MS = 400;

export function RunPanel({
  fetchCurrentJob,
  onJobDone,
  startMeasureJob,
}: RunPanelProps) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const isRunning = snapshot?.status === "running" || isStarting;
  const stepIndex = snapshot?.step_index ?? 0;
  const stepCount = snapshot?.step_count ?? 9;
  const sentence = snapshot?.sentence ?? "";
  const error = snapshot?.status === "failed" ? snapshot.error : startError;
  const visibleError = error === sentence ? null : error;
  const sentenceClassName =
    snapshot?.status === "failed"
      ? "run__sentence run__sentence--error"
      : "run__sentence";

  const clearPoll = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const publishSnapshot = useCallback(
    (nextSnapshot: JobSnapshot) => {
      setSnapshot(nextSnapshot);

      if (nextSnapshot.status === "done" && nextSnapshot.result) {
        onJobDone(nextSnapshot.result);
      }
    },
    [onJobDone],
  );

  const pollCurrentJob = useCallback(async () => {
    clearPoll();

    try {
      const nextSnapshot = await fetchCurrentJob();
      publishSnapshot(nextSnapshot);
      setStartError(null);
    } catch (errorValue) {
      setStartError(errorMessage(errorValue));
    }
  }, [clearPoll, publishSnapshot]);

  useEffect(() => {
    if (snapshot?.status === "running") {
      timerRef.current = window.setTimeout(pollCurrentJob, POLL_INTERVAL_MS);
    }

    return clearPoll;
  }, [clearPoll, pollCurrentJob, snapshot?.status]);

  const handleMeasure = useCallback(async () => {
    setIsStarting(true);
    setStartError(null);

    try {
      await startMeasureJob();
      await pollCurrentJob();
    } catch (errorValue) {
      if (isConflictError(errorValue)) {
        await pollCurrentJob();
        return;
      }

      setStartError(errorMessage(errorValue));
    } finally {
      setIsStarting(false);
    }
  }, [pollCurrentJob, startMeasureJob]);

  return (
    <section className="run" aria-labelledby="run-heading">
      <div className="run__header">
        <p className="run__kicker">Run</p>
        <h2 className="run__heading" id="run-heading">
          Measurement job
        </h2>
      </div>

      <div className="run__controls">
        <button
          className="run__button"
          type="button"
          disabled={isRunning}
          onClick={handleMeasure}
        >
          Measure scene
        </button>

        <div className="run__status" role="status" aria-live="polite">
          <span
            className={isRunning ? "run__spinner run__spinner--active" : "run__spinner"}
            aria-hidden="true"
          />
          <span className="run__step">
            {stepIndex} of {stepCount}
          </span>
          {sentence ? <span className={sentenceClassName}>{sentence}</span> : null}
          {visibleError ? <span className="run__error">{visibleError}</span> : null}
        </div>
      </div>
    </section>
  );
}

function isConflictError(errorValue: unknown): boolean {
  return getStatus(errorValue) === 409;
}

function getStatus(errorValue: unknown): number | null {
  if (typeof errorValue !== "object" || errorValue === null) {
    return null;
  }

  const candidate = errorValue as {
    status?: unknown;
    response?: { status?: unknown };
  };
  const status = candidate.status ?? candidate.response?.status;
  return typeof status === "number" ? status : null;
}

function errorMessage(errorValue: unknown): string {
  if (errorValue instanceof Error && errorValue.message) {
    return errorValue.message;
  }

  return "Could not run the measurement job.";
}
