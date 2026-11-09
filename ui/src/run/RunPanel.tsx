import { useCallback, useEffect, useRef, useState } from "react";

import * as sceneApi from "@/api";
import type { JobSnapshot } from "@/types";

import "./run.css";

type JobResult = NonNullable<(JobSnapshot & { result?: unknown | null })["result"]>;

type RunPanelProps = {
  initialJob?: JobSnapshot | null;
  onJobSnapshot?: (snapshot: JobSnapshot) => void;
  onSnapshot?: (snapshot: JobSnapshot) => void;
  onJobResult?: (result: JobResult) => void;
  onResult?: (result: JobResult) => void;
};

type StartResponse = {
  job_id: string;
  status: "running";
};

type ApiModule = {
  startMeasureJob?: () => Promise<StartResponse>;
  postMeasureJob?: () => Promise<StartResponse>;
  startMeasurementJob?: () => Promise<StartResponse>;
  fetchCurrentJob?: () => Promise<JobSnapshot>;
  fetchCurrentJobSnapshot?: () => Promise<JobSnapshot>;
  getCurrentJob?: () => Promise<JobSnapshot>;
};

const POLL_INTERVAL_MS = 400;

export function RunPanel({
  initialJob = null,
  onJobSnapshot,
  onSnapshot,
  onJobResult,
  onResult,
}: RunPanelProps) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(initialJob);
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const isRunning = snapshot?.status === "running" || isStarting;
  const stepIndex = snapshot?.step_index ?? 0;
  const stepCount = snapshot?.step_count ?? 9;
  const sentence = snapshot?.sentence ?? "";
  const error = snapshot?.status === "failed" ? snapshot.error : startError;

  const clearPoll = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const publishSnapshot = useCallback(
    (nextSnapshot: JobSnapshot) => {
      setSnapshot(nextSnapshot);
      onJobSnapshot?.(nextSnapshot);
      onSnapshot?.(nextSnapshot);

      if (nextSnapshot.status === "done" && nextSnapshot.result) {
        onJobResult?.(nextSnapshot.result as JobResult);
        onResult?.(nextSnapshot.result as JobResult);
      }
    },
    [onJobResult, onJobSnapshot, onResult, onSnapshot],
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
  }, [pollCurrentJob]);

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
          {sentence ? <span className="run__sentence">{sentence}</span> : null}
          {error ? <span className="run__error">{error}</span> : null}
        </div>
      </div>
    </section>
  );
}

async function startMeasureJob(): Promise<StartResponse> {
  const api = sceneApi as ApiModule;
  const helper =
    api.startMeasureJob ?? api.postMeasureJob ?? api.startMeasurementJob;

  if (helper) {
    return helper();
  }

  const response = await fetch("/api/jobs/measure", {
    method: "POST",
    body: "",
  });

  if (!response.ok) {
    throw Object.assign(new Error("Could not start measurement job"), {
      status: response.status,
    });
  }

  return response.json() as Promise<StartResponse>;
}

async function fetchCurrentJob(): Promise<JobSnapshot> {
  const api = sceneApi as ApiModule;
  const helper =
    api.fetchCurrentJob ?? api.fetchCurrentJobSnapshot ?? api.getCurrentJob;

  if (helper) {
    return helper();
  }

  const response = await fetch("/api/jobs/current");

  if (!response.ok) {
    throw Object.assign(new Error("Could not fetch current measurement job"), {
      status: response.status,
    });
  }

  return response.json() as Promise<JobSnapshot>;
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
