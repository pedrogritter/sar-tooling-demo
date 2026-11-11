import type {
  AnalysisToolsResponse,
  CatalogItemDetail,
  CatalogSearchResponse,
  DownloadAccepted,
  DownloadSnapshot,
  JobSnapshot,
  LibraryResponse,
  MeasureJobAccepted,
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
  return requestJson<SceneResponse>(`/api/scenes/${encodeURIComponent(sceneId)}`)
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
