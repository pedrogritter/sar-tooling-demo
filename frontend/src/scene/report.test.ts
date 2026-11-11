import {
  beltText,
  briefingBlocks,
  failedSections,
  partnerOptions,
  runnableIds,
  splitPlan,
  toolLabel,
} from "@/scene/report"
import type { ReportPlan, ReportSection } from "@/types"

const PLAN: ReportPlan = {
  selected: ["open-water", "built-up"],
  waiting: ["amplitude-change"],
  locked: [
    { id: "dwell-motion", reason: "This scene has no dwell video." },
    { id: "sea-state", reason: null },
  ],
  catalogue_only: [],
  partner_id: null,
}

function section(overrides: Partial<ReportSection>): ReportSection {
  return {
    tool_id: "open-water",
    status: "done",
    measurement: null,
    briefing_md: "Model text. Limit sentence.",
    briefing_source: "model",
    overview_url: null,
    partner_id: null,
    ...overrides,
  }
}

describe("splitPlan", () => {
  it("splits the plan into selected, waiting, and locked", () => {
    const split = splitPlan(PLAN)

    expect(split.selected).toEqual(["open-water", "built-up"])
    expect(split.waiting).toEqual(["amplitude-change"])
    expect(split.locked).toEqual([
      { id: "dwell-motion", reason: "This scene has no dwell video." },
      { id: "sea-state", reason: null },
    ])
  })

  it("never lists a tool in two groups", () => {
    const split = splitPlan(PLAN)
    const lockedIds = split.locked.map((tool) => tool.id)

    expect(split.selected.some((id) => lockedIds.includes(id))).toBe(false)
    expect(split.waiting.some((id) => lockedIds.includes(id))).toBe(false)
  })

  it("rejects a plan that is not the server's shape", () => {
    expect(() => splitPlan({} as ReportPlan)).toThrow(/plan/i)
    expect(() =>
      splitPlan({ ...PLAN, locked: ["dwell-motion"] } as unknown as ReportPlan)
    ).toThrow(/plan/i)
  })
})

describe("runnableIds", () => {
  it("posts selected and waiting ids and no locked id", () => {
    const ids = runnableIds({
      ...PLAN,
      selected: ["open-water", "dwell-motion"],
    })

    expect(ids).toEqual(["open-water", "amplitude-change"])
    expect(ids).not.toContain("dwell-motion")
  })
})

describe("beltText", () => {
  it("keeps the stored briefing when the source is the belt", () => {
    const text = beltText(
      section({ briefing_source: "belt", briefing_md: "The belt's text." })
    )

    expect(text).toBe("The belt's text.")
  })

  it("is null when the model's text is the one shown", () => {
    expect(beltText(section({ briefing_source: "model" }))).toBeNull()
  })
})

describe("partnerOptions", () => {
  it("uses the partner the plan lists", () => {
    expect(
      partnerOptions({ ...PLAN, partner_id: "B" }, ["A", "B", "C"])
    ).toEqual(["B"])
  })

  it("falls back to the scene's partners when the plan has none", () => {
    expect(partnerOptions(PLAN, ["A", "B"])).toEqual(["A", "B"])
    expect(partnerOptions(null, ["A"])).toEqual(["A"])
  })
})

describe("failedSections", () => {
  it("counts failed sections even when the job finished", () => {
    const failed = failedSections({
      scene_id: "S",
      question: "q",
      sections: [
        section({ tool_id: "open-water", status: "done" }),
        section({ tool_id: "built-up", status: "failed" }),
        section({ tool_id: "dwell-motion", status: "locked" }),
      ],
    })

    expect(failed.map((item) => item.tool_id)).toEqual(["built-up"])
  })
})

describe("toolLabel", () => {
  it("names a tool from the belt list and falls back to its id", () => {
    expect(toolLabel("open-water")).toBe("Open water")
    expect(toolLabel("not-a-tool")).toBe("not-a-tool")
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
