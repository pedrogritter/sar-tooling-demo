import type {
  AnalysisToolsResponse,
  CatalogItemDetail,
  CatalogSearchResponse,
  DownloadAccepted,
  DownloadSnapshot,
  JobSnapshot,
  LibraryResponse,
  MeasureJobAccepted,
  ModelKeyStatus,
  Report,
  SceneResponse,
} from "@/types"

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

export class DownloadConflictError extends ApiError {
  constructor(message = "A download is already running.") {
    super(message, 409)
    this.name = "DownloadConflictError"
  }
}

export class MeasureJobConflictError extends ApiError {
  constructor(message = "A measurement job is already running.") {
    super(message, 409)
    this.name = "MeasureJobConflictError"
  }
}

export async function fetchScene(): Promise<SceneResponse> {
  return requestJson<SceneResponse>("/api/scene")
}

export async function startMeasureJob(): Promise<MeasureJobAccepted> {
  try {
    return await requestJson<MeasureJobAccepted>("/api/jobs/measure", {
      method: "POST",
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new MeasureJobConflictError()
    }

    throw error
  }
}

export async function fetchCurrentJob(): Promise<JobSnapshot> {
  return requestJson<JobSnapshot>("/api/jobs/current")
}

export async function fetchAnalysisTools(
  sceneId: string
): Promise<AnalysisToolsResponse> {
  return requestJson<AnalysisToolsResponse>(
    `/api/scenes/${encodeURIComponent(sceneId)}/tools`
  )
}

export async function startAnalysisJob(
  sceneId: string,
  toolId: string,
  partnerId: string | null
): Promise<MeasureJobAccepted> {
  try {
    return await requestJson<MeasureJobAccepted>("/api/jobs/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scene_id: sceneId,
        tool_id: toolId,
        partner_id: partnerId,
      }),
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new MeasureJobConflictError()
    }

    throw error
  }
}

export async function fetchSceneById(sceneId: string): Promise<SceneResponse> {
  return requestJson<SceneResponse>(
    `/api/scenes/${encodeURIComponent(sceneId)}`
  )
}

export async function fetchLibrary(): Promise<LibraryResponse> {
  return requestJson<LibraryResponse>("/api/library")
}

export async function clearDemoData(): Promise<{
  cleared: boolean
  note: string
}> {
  return requestJson("/api/demo/clear", { method: "POST" })
}

export async function fetchCatalog(
  path: string
): Promise<CatalogSearchResponse> {
  return requestJson<CatalogSearchResponse>(path)
}

export async function fetchCatalogItem(
  sceneId: string
): Promise<CatalogItemDetail> {
  return requestJson<CatalogItemDetail>(
    `/api/catalog/items/${encodeURIComponent(sceneId)}`
  )
}

export async function refreshCatalog(): Promise<void> {
  await requestJson("/api/catalog/refresh", { method: "POST" })
}

export async function startDownload(
  itemId: string,
  assets: string[]
): Promise<DownloadAccepted> {
  try {
    return await requestJson<DownloadAccepted>("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, assets }),
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new DownloadConflictError()
    }

    throw error
  }
}

export async function fetchDownload(): Promise<DownloadSnapshot> {
  return requestJson<DownloadSnapshot>("/api/downloads/current")
}

/** The saved report for a scene. Partial while a report job runs. */
export async function fetchReport(sceneId: string): Promise<Report> {
  return requestReportJson<Report>(reportPath(sceneId))
}

/**
 * The sentence a missing key returns as 409. Any other 409 means a measurement
 * is already running and the page keeps watching that job.
 */
export const REPORT_KEY_REQUIRED = "Set OPENAI_API_KEY to ask a question."

/** True when Start was refused because this server has no OpenAI key. */
export function isReportKeyRequiredError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.message.trim() === REPORT_KEY_REQUIRED
  )
}

/**
 * Start the one report job. `partnerId` null is this scene only. A scene id
 * adds that partner. The body has no question and no tool ids.
 */
export async function startReportRun(
  sceneId: string,
  partnerId: string | null
): Promise<MeasureJobAccepted> {
  return startReportJob(`${reportPath(sceneId)}/run`, {
    partner_id: partnerId,
  })
}

/** Whether this server has a model key. The body never contains the key. */
export async function fetchModelKey(): Promise<ModelKeyStatus> {
  return requestReportJson<ModelKeyStatus>("/api/report/key")
}

/**
 * Keep a key for this server process. A key that arrived from the environment
 * is refused, and the response does not echo the key.
 */
export async function saveModelKey(apiKey: string): Promise<ModelKeyStatus> {
  return requestReportJson<ModelKeyStatus>("/api/report/key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  })
}

/** The PDF of the saved report. */
export function reportPdfUrl(sceneId: string): string {
  return `/api/scenes/${encodeURIComponent(sceneId)}/report.pdf`
}

function reportPath(sceneId: string): string {
  return `/api/scenes/${encodeURIComponent(sceneId)}/report`
}

async function startReportJob(
  path: string,
  payload: Record<string, unknown>
): Promise<MeasureJobAccepted> {
  try {
    return await requestReportJson<MeasureJobAccepted>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  } catch (error) {
    // A missing key stays a plain 409 so Start does not watch a job that
    // never began. Every other 409 is a measurement already running.
    if (isReportKeyRequiredError(error)) {
      throw error
    }

    if (error instanceof ApiError && error.status === 409) {
      throw new MeasureJobConflictError(error.message || undefined)
    }

    throw error
  }
}

/**
 * Like `requestJson`, but the report routes answer errors as plain text, for
 * example `Set OPENAI_API_KEY to ask a question.` That text is the message.
 */
async function requestReportJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(input, init)

  if (!response.ok) {
    throw new ApiError(await plainErrorMessage(response), response.status)
  }

  return (await response.json()) as T
}

async function plainErrorMessage(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}`
  const text = (await response.text().catch(() => "")).trim()

  if (!text) {
    return fallback
  }

  try {
    const body = JSON.parse(text) as unknown

    if (isRecord(body) && typeof body.error === "string") {
      return body.error
    }

    if (isRecord(body) && typeof body.message === "string") {
      return body.message
    }

    // A measurement already running is JSON `{ "status": "running" }`.
    if (isRecord(body) && body.status === "running") {
      return "A measurement job is already running."
    }

    return fallback
  } catch {
    return text
  }
}

async function requestJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(input, init)

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }

  return (await response.json()) as T
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}`

  try {
    const body = (await response.json()) as unknown

    if (isRecord(body) && typeof body.error === "string") {
      return body.error
    }

    if (isRecord(body) && typeof body.message === "string") {
      return body.message
    }
  } catch {
    return fallback
  }

  return fallback
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}
