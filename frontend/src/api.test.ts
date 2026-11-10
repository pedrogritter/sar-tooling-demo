import {
  ApiError,
  MeasureJobConflictError,
  fetchCurrentJob,
  fetchScene,
  startMeasureJob,
} from "@/api"

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("scene api", () => {
  const fetchMock = jest.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    global.fetch = fetchMock as typeof fetch
  })

  it("loads the scene document", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ scene_id: "ICEYE" }))

    await expect(fetchScene()).resolves.toEqual({ scene_id: "ICEYE" })
    expect(fetchMock).toHaveBeenCalledWith("/api/scene", undefined)
  })

  it("turns HTTP 409 into a conflict error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "running" }, 409))

    await expect(startMeasureJob()).rejects.toBeInstanceOf(
      MeasureJobConflictError
    )
  })

  it("rethrows other start failures", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "missing grd" }, 400))

    await expect(startMeasureJob()).rejects.toThrow("missing grd")
  })

  it("uses the error string from a JSON body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "missing grd" }, 500))

    const error = await fetchCurrentJob().catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ message: "missing grd", status: 500 })
  })

  it("uses a message field when error is absent", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: "busy" }, 503))

    await expect(fetchScene()).rejects.toThrow("busy")
  })

  it("falls back when the body is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("nope", { status: 502 }))

    await expect(fetchScene()).rejects.toThrow("Request failed with status 502")
  })

  it("falls back when the JSON body has no message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "no" }, 400))

    await expect(fetchScene()).rejects.toThrow("Request failed with status 400")
  })
})
