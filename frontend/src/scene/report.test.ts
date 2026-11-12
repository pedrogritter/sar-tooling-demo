import {
  activeRailStep,
  briefingBlocks,
  eligiblePartners,
  figureViews,
  heldViews,
  normalizeReport,
  progressPercent,
  reportHasDocument,
  reportIsComplete,
  reportPartnerId,
  reportProgress,
  reportRail,
  shouldLoadReport,
  statusLabel,
  synthesisText,
  toolLabel,
} from "@/scene/report"
import type { Report, ReportSection } from "@/types"

function section(overrides: Partial<ReportSection> = {}): ReportSection {
  return {
    tool_id: "open-water",
    status: "done",
    measurement: {
      summary: [{ label: "Water area", value: "1 km²" }],
      limit: "A bright return stays a bright radar return.",
    },
    briefing_md: "Section text.",
    briefing_source: "model",
    overview_url: "/overview.png",
    partner_id: null,
    progress_note: "",
    ...overrides,
  }
}

function report(overrides: Partial<Report> = {}): Report {
  return {
    scene_id: "S",
    question: "",
    partner_id: null,
    phase: "done",
    tool_order: ["open-water", "built-up"],
    synthesis_md: "The lead.",
    synthesis_source: "model",
    sections: [],
    ...overrides,
  }
}

describe("eligiblePartners", () => {
  it("reads the amplitude-change partner list and hides an empty one", () => {
    expect(
      eligiblePartners([
        { id: "open-water", partners: [] },
        { id: "amplitude-change", partners: ["A", "B"] },
      ])
    ).toEqual(["A", "B"])
    expect(eligiblePartners([{ id: "open-water", partners: ["A"] }])).toEqual(
      []
    )
    expect(
      eligiblePartners([{ id: "amplitude-change", partners: [] }])
    ).toEqual([])
    expect(
      eligiblePartners([
        { id: "amplitude-change", locked: true, partners: ["A"] },
      ])
    ).toEqual([])
  })
})

describe("reportPartnerId", () => {
  it("sends null for this scene only and the id when a partner is chosen", () => {
    expect(reportPartnerId("")).toBeNull()
    expect(reportPartnerId("  ")).toBeNull()
    expect(reportPartnerId("ICEYE_B")).toBe("ICEYE_B")
  })
})

describe("normalizeReport", () => {
  it("keeps a report that already matches the contract", () => {
    const saved = report({
      phase: "running",
      partner_id: "ICEYE_B",
      sections: [section({ progress_note: "Looking at dark water." })],
    })

    expect(normalizeReport(saved)).toEqual(saved)
  })

  it("treats an older file with sections as a finished report and blanks a missing note", () => {
    const saved = normalizeReport({
      scene_id: "S",
      question: "What is dark?",
      sections: [
        {
          tool_id: "open-water",
          status: "done",
          measurement: null,
          briefing_md: "Belt text.",
          briefing_source: "belt",
          overview_url: null,
          partner_id: null,
        },
      ],
    })

    expect(saved.phase).toBe("done")
    expect(saved.question).toBe("What is dark?")
    expect(saved.partner_id).toBeNull()
    expect(saved.tool_order).toEqual(["open-water"])
    expect(saved.synthesis_md).toBe("")
    expect(saved.synthesis_source).toBe("belt")
    expect(saved.sections[0]?.progress_note).toBe("")
  })

  it("treats an empty older file as a finished report with nothing to show", () => {
    const saved = normalizeReport({
      scene_id: "S",
      question: "",
      sections: [],
    })

    expect(saved.phase).toBe("done")
    expect(reportHasDocument(saved)).toBe(false)
    expect(reportIsComplete(saved)).toBe(false)
  })
})

describe("activeRailStep", () => {
  it("selects Plan while the run is still choosing an order", () => {
    expect(activeRailStep(report({ phase: "planning" }), true)).toBe(
      "step:plan"
    )
    expect(activeRailStep(null, true)).toBe("step:plan")
    expect(
      activeRailStep(report({ phase: "done", sections: [section()] }), true)
    ).toBe("step:plan")
  })

  it("selects the running tool ahead of an earlier id that has no section yet", () => {
    const saved = report({
      phase: "running",
      tool_order: ["open-water", "built-up", "dwell-motion"],
      sections: [
        section({
          tool_id: "built-up",
          status: "running",
          progress_note: "Bright clusters.",
        }),
      ],
    })

    expect(activeRailStep(saved, true)).toBe("tool:built-up")
  })

  it("selects the first id that has no section yet", () => {
    const saved = report({
      phase: "running",
      tool_order: ["open-water", "built-up"],
      sections: [section({ tool_id: "open-water", status: "done" })],
    })

    expect(activeRailStep(saved, true)).toBe("tool:built-up")
  })

  it("selects Write the report once every ordered tool has finished", () => {
    const saved = report({
      phase: "running",
      sections: [
        section({ status: "done" }),
        section({ tool_id: "built-up", status: "locked" }),
      ],
    })

    expect(activeRailStep(saved, true)).toBe("step:write")
    expect(activeRailStep(report({ phase: "writing" }), true)).toBe(
      "step:write"
    )
  })

  it("selects no row once the report is finished and the job has stopped", () => {
    expect(activeRailStep(report({ phase: "done" }), false)).toBeNull()
    expect(activeRailStep(null, false)).toBeNull()
  })
})

describe("reportRail", () => {
  it("lists Plan, each ordered tool, then Write the report", () => {
    const rows = reportRail(
      report({
        phase: "running",
        tool_order: ["open-water", "built-up", "dwell-motion"],
        sections: [
          section({ status: "done", progress_note: "Already said." }),
          section({
            tool_id: "built-up",
            status: "running",
            progress_note: "Bright clusters on land.",
          }),
        ],
      }),
      true,
      "Job sentence."
    )

    expect(rows.map((row) => [row.label, row.status, row.active])).toEqual([
      ["Plan", "", false],
      ["Open water", "Written", false],
      ["Built-up return", "Measuring", true],
      ["Dwell motion", "Queued", false],
      ["Write the report", "", false],
    ])
    expect(rows.map((row) => row.note)).toEqual([
      null,
      null,
      "Bright clusters on land.",
      null,
      null,
    ])
    expect(rows[1]?.toolId).toBe("open-water")
    expect(rows[2]?.toolId).toBeNull()
    expect(rows[3]?.toolId).toBeNull()
  })

  it("uses the job sentence when the active tool has no progress note", () => {
    const rows = reportRail(
      report({
        phase: "planning",
        tool_order: ["open-water"],
      }),
      true,
      "Choosing an order."
    )

    expect(rows[0]).toMatchObject({
      label: "Plan",
      active: true,
      note: "Choosing an order.",
    })
  })

  it("labels locked and failed tools and drops narrator lines when the run is done", () => {
    const rows = reportRail(
      report({
        phase: "done",
        tool_order: ["dwell-motion", "sea-state"],
        sections: [
          section({
            tool_id: "dwell-motion",
            status: "locked",
            progress_note: "A joke.",
          }),
          section({
            tool_id: "sea-state",
            status: "failed",
            progress_note: "Another joke.",
          }),
        ],
      }),
      false,
      "The report is written."
    )

    expect(rows.map((row) => [row.label, row.status])).toEqual([
      ["Plan", ""],
      ["Dwell motion", "Cannot run"],
      ["Sea state", "Failed"],
      ["Write the report", ""],
    ])
    expect(rows.every((row) => row.note === null && !row.active)).toBe(true)
  })

  it("stays empty before a report has been started", () => {
    expect(reportRail(null, false, "")).toEqual([])
    expect(
      reportRail(
        report({
          phase: "done",
          tool_order: [],
          synthesis_md: "",
          sections: [],
        }),
        false,
        ""
      )
    ).toEqual([])
  })
})

describe("synthesisText", () => {
  it("shows the lead only after the run is done", () => {
    expect(synthesisText(report({ phase: "done" }))).toBe("The lead.")
    expect(
      synthesisText(report({ phase: "writing", synthesis_md: "Half." }))
    ).toBeNull()
    expect(
      synthesisText(report({ phase: "done", synthesis_md: "  " }))
    ).toBeNull()
  })
})

describe("figureViews", () => {
  it("follows tool order and keeps the picture, the rows, and the limit", () => {
    const figures = figureViews(
      report({
        tool_order: ["built-up", "open-water"],
        sections: [
          section({
            tool_id: "open-water",
            overview_url: "/water.png",
            progress_note: "A joke about dark water.",
            briefing_md: "A model essay that is not the figure.",
          }),
          section({
            tool_id: "built-up",
            overview_url: "/built.png",
            measurement: {
              summary: [{ label: "Clusters", value: "4" }],
              limit: "Not a building height.",
            },
            partner_id: "ICEYE_B",
          }),
          section({ tool_id: "dwell-motion", status: "running" }),
        ],
      })
    )

    expect(figures.map((figure) => figure.toolId)).toEqual([
      "built-up",
      "open-water",
    ])
    expect(figures[0]).toMatchObject({
      label: "Built-up return",
      status: "Written",
      imageUrl: "/built.png",
      summary: [{ label: "Clusters", value: "4" }],
      limit: "Not a building height.",
      partnerId: "ICEYE_B",
    })
    expect(JSON.stringify(figures)).not.toContain("A joke")
    expect(JSON.stringify(figures)).not.toContain("model essay")
  })
})

describe("heldViews", () => {
  it("lists locked tools, then failed tools, then a legacy waiting tool", () => {
    const held = heldViews(
      report({
        tool_order: ["amplitude-change", "dwell-motion", "sea-state"],
        sections: [
          section({
            tool_id: "sea-state",
            status: "failed",
            briefing_md: "The raster raised.",
            progress_note: "A joke.",
          }),
          section({
            tool_id: "dwell-motion",
            status: "locked",
            briefing_md: "This scene has no dwell video.",
            progress_note: "Another joke.",
          }),
          section({
            tool_id: "amplitude-change",
            status: "waiting",
            briefing_md: "Waiting text.",
          }),
          section({ tool_id: "open-water", status: "done" }),
        ],
      })
    )

    expect(held.map((item) => [item.label, item.status, item.text])).toEqual([
      ["Dwell motion", "Cannot run", "This scene has no dwell video."],
      ["Sea state", "Failed", "The raster raised."],
      ["Amplitude change", "Needs a second scene", "Waiting text."],
    ])
    expect(JSON.stringify(held)).not.toContain("A joke")
    expect(JSON.stringify(held)).not.toContain("Another joke")
  })
})

describe("reportProgress", () => {
  it("counts finished tools over the ordered set", () => {
    const saved = report({
      tool_order: ["open-water", "built-up", "dwell-motion", "sea-state"],
      sections: [
        section({ status: "done" }),
        section({ tool_id: "built-up", status: "locked" }),
        section({ tool_id: "dwell-motion", status: "failed" }),
        section({ tool_id: "sea-state", status: "running" }),
      ],
    })

    expect(reportProgress(saved)).toEqual({ completed: 3, total: 4 })
    expect(progressPercent(3, 4)).toBe(75)
    expect(progressPercent(0, 0)).toBe(0)
  })

  it("does not count a legacy waiting section as finished", () => {
    const saved = report({
      tool_order: ["amplitude-change"],
      sections: [section({ tool_id: "amplitude-change", status: "waiting" })],
    })

    expect(reportProgress(saved)).toEqual({ completed: 0, total: 1 })
  })
})

describe("reportIsComplete", () => {
  it("is complete only when a finished report has something to read", () => {
    expect(reportIsComplete(report({ sections: [section()] }))).toBe(true)
    expect(
      reportIsComplete(report({ phase: "running", sections: [section()] }))
    ).toBe(false)
    expect(reportIsComplete(report({ synthesis_md: "", sections: [] }))).toBe(
      false
    )
  })
})

describe("shouldLoadReport", () => {
  it("loads the report for a job that is running, done, or failed", () => {
    expect(shouldLoadReport("running")).toBe(true)
    expect(shouldLoadReport("done")).toBe(true)
    expect(shouldLoadReport("failed")).toBe(true)
  })

  it("does not load it for an idle job", () => {
    expect(shouldLoadReport("idle")).toBe(false)
  })
})

describe("toolLabel", () => {
  it("names a tool from the belt list and falls back to its id", () => {
    expect(toolLabel("open-water")).toBe("Open water")
    expect(toolLabel("not-a-tool")).toBe("not-a-tool")
  })
})

describe("statusLabel", () => {
  it("uses plain words for each report status", () => {
    expect(statusLabel("queued")).toBe("Queued")
    expect(statusLabel("running")).toBe("Measuring")
    expect(statusLabel("done")).toBe("Written")
    expect(statusLabel("waiting")).toBe("Needs a second scene")
    expect(statusLabel("locked")).toBe("Cannot run")
    expect(statusLabel("failed")).toBe("Failed")
    expect(statusLabel("custom")).toBe("custom")
  })
})

describe("briefingBlocks", () => {
  it("reads a heading, a paragraph, and a bullet list", () => {
    const blocks = briefingBlocks(
      "# Open water\n\nDark for the same reason.\n\n- Water area: 24.55 km²\n- Water fraction: 0.992\n"
    )

    expect(blocks).toEqual([
      { kind: "heading", text: "Open water" },
      { kind: "paragraph", text: "Dark for the same reason." },
      {
        kind: "list",
        items: ["Water area: 24.55 km²", "Water fraction: 0.992"],
      },
    ])
  })

  it("joins wrapped lines into one paragraph and drops blanks", () => {
    expect(briefingBlocks("one\ntwo\n\n\n")).toEqual([
      { kind: "paragraph", text: "one two" },
    ])
    expect(briefingBlocks("")).toEqual([])
  })
})
