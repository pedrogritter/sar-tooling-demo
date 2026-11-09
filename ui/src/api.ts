import type { JobSnapshot, MeasureJobAccepted, SceneResponse } from "@/types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export class MeasureJobConflictError extends ApiError {
  constructor(message = "A measurement job is already running.") {
    super(message, 409);
    this.name = "MeasureJobConflictError";
  }
}

export async function fetchScene(): Promise<SceneResponse> {
  return requestJson<SceneResponse>("/api/scene");
}

export async function startMeasureJob(): Promise<MeasureJobAccepted> {
  try {
    return await requestJson<MeasureJobAccepted>("/api/jobs/measure", {
      method: "POST",
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new MeasureJobConflictError();
    }

    throw error;
  }
}

export async function fetchCurrentJob(): Promise<JobSnapshot> {
  return requestJson<JobSnapshot>("/api/jobs/current");
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }

  return (await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}`;

  try {
    const body = (await response.json()) as unknown;

    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      typeof body.error === "string"
    ) {
      return body.error;
    }

    if (
      body &&
      typeof body === "object" &&
      "message" in body &&
      typeof body.message === "string"
    ) {
      return body.message;
    }
  } catch {
    return fallback;
  }

  return fallback;
}
