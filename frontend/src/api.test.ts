import {
  ApiError,
  MeasureJobConflictError,
  fetchCurrentJob,
  fetchModelKey,
  fetchScene,
  isReportKeyRequiredError,
  reportPdfUrl,
  saveModelKey,
  startAnalysisJob,
  startReportRun,
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

  it("posts the scene, the tool, and the partner", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-1", status: "running" }, 202)
    )

    await startAnalysisJob("ICEYE_TEST", "amplitude-change", "ICEYE_OTHER")

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scene_id: "ICEYE_TEST",
        tool_id: "amplitude-change",
        partner_id: "ICEYE_OTHER",
      }),
    })
  })

  it("sends a null partner when the tool does not need one", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-2", status: "running" }, 202)
    )

    await startAnalysisJob("ICEYE_TEST", "open-water", null)

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body)) as {
      partner_id: string | null
    }
    expect(body.partner_id).toBeNull()
  })

  it("turns an analysis 409 into a conflict error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "running" }, 409))

    await expect(
      startAnalysisJob("ICEYE_TEST", "open-water", null)
    ).rejects.toBeInstanceOf(MeasureJobConflictError)
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

describe("report api", () => {
  const fetchMock = jest.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    global.fetch = fetchMock as typeof fetch
  })

  it("posts a null partner when the report is this scene only", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-3", status: "running" }, 202)
    )

    await startReportRun("ICEYE_TEST", null)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/scenes/ICEYE_TEST/report/run",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ partner_id: null }),
      }
    )
  })

  it("posts the chosen partner scene id", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-4", status: "running" }, 202)
    )

    await startReportRun("ICEYE_TEST", "ICEYE_B")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/scenes/ICEYE_TEST/report/run",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ partner_id: "ICEYE_B" }),
      }
    )
  })

  it("keeps the missing-key 409 as a plain error", async () => {
    fetchMock.mockResolvedValue(
      new Response("Set OPENAI_API_KEY to ask a question.\n", { status: 409 })
    )

    const error = await startReportRun("ICEYE_TEST", null).catch(
      (caught: unknown) => caught
    )

    expect(isReportKeyRequiredError(error)).toBe(true)
    expect(error).not.toBeInstanceOf(MeasureJobConflictError)
    expect(error).toMatchObject({
      status: 409,
      message: "Set OPENAI_API_KEY to ask a question.",
    })
  })

  it("reads a running-job 409 as the measurement conflict", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "running" }, 409))

    const error = await startReportRun("ICEYE_TEST", null).catch(
      (caught: unknown) => caught
    )

    expect(error).toBeInstanceOf(MeasureJobConflictError)
    expect(error).toMatchObject({
      status: 409,
      message: "A measurement job is already running.",
    })
  })

  it("turns any other 409 into a conflict and keeps the message", async () => {
    fetchMock.mockResolvedValue(
      new Response("A measurement is already running.\n", { status: 409 })
    )

    const error = await startReportRun("ICEYE_TEST", null).catch(
      (caught: unknown) => caught
    )

    expect(error).toBeInstanceOf(MeasureJobConflictError)
    expect(error).toMatchObject({
      status: 409,
      message: "A measurement is already running.",
    })
  })

  it("keeps a 400 when the partner is ineligible or nothing can run", async () => {
    fetchMock.mockResolvedValue(
      new Response("Nothing on this scene can run.\n", { status: 400 })
    )

    const error = await startReportRun("ICEYE_TEST", "NOPE").catch(
      (caught: unknown) => caught
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error).not.toBeInstanceOf(MeasureJobConflictError)
    expect(error).toMatchObject({
      status: 400,
      message: "Nothing on this scene can run.",
    })
  })

  it("points the PDF link at the report route", () => {
    expect(reportPdfUrl("ICEYE_TEST")).toBe("/api/scenes/ICEYE_TEST/report.pdf")
  })

  it("reads the key status and never expects the key back", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ configured: false, source: "unset" })
    )

    await expect(fetchModelKey()).resolves.toEqual({
      configured: false,
      source: "unset",
    })
    expect(fetchMock).toHaveBeenCalledWith("/api/report/key", undefined)
  })

  it("posts a key and keeps the response status", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ configured: true, source: "session" })
    )

    await expect(saveModelKey("sk-test")).resolves.toEqual({
      configured: true,
      source: "session",
    })
    expect(fetchMock).toHaveBeenCalledWith("/api/report/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: "sk-test" }),
    })
  })
})
