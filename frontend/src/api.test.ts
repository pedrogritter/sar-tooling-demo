import {
  ApiError,
  MeasureJobConflictError,
  fetchCurrentJob,
  fetchScene,
  planReport,
  reportPdfUrl,
  startAnalysisJob,
  startReportAmplitude,
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

  it("posts the question to the plan route", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ selected: [] }))

    await planReport("ICEYE_TEST", "What is dark?")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/scenes/ICEYE_TEST/report/plan",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: "What is dark?" }),
      }
    )
  })

  it("keeps the plain text of a 409 plan answer", async () => {
    fetchMock.mockResolvedValue(
      new Response("Set OPENAI_API_KEY to ask a question.\n", { status: 409 })
    )

    const error = await planReport("ICEYE_TEST", "q").catch(
      (caught: unknown) => caught
    )

    expect(error).toMatchObject({
      status: 409,
      message: "Set OPENAI_API_KEY to ask a question.",
    })
  })

  it("posts the question and the tool ids to the run route", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-3", status: "running" }, 202)
    )

    await startReportRun("ICEYE_TEST", "q", ["open-water"])

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/scenes/ICEYE_TEST/report/run",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: "q", tool_ids: ["open-water"] }),
      }
    )
  })

  it("turns a running report job into a conflict error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "running" }, 409))

    await expect(
      startReportAmplitude("ICEYE_TEST", "ICEYE_B")
    ).rejects.toBeInstanceOf(MeasureJobConflictError)
  })

  it("points the PDF link at the report route", () => {
    expect(reportPdfUrl("ICEYE_TEST")).toBe("/api/scenes/ICEYE_TEST/report.pdf")
  })
})
