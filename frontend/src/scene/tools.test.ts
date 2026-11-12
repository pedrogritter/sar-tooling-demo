import {
  SHELL_TOOLS,
  isAnalysisTool,
  isGroupOpen,
  selectTool,
  toolById,
} from "@/scene/tools"

describe("selected tool", () => {
  it("selects a tool and closes it when the same tool is chosen again", () => {
    const open = selectTool(null, "catalog")
    expect(open).toBe("catalog")
    expect(selectTool(open, "catalog")).toBeNull()
  })

  it("replaces the open tool", () => {
    expect(selectTool("preview", "open-water")).toBe("open-water")
  })

  it("falls back to Preview for an unknown id", () => {
    expect(toolById("facts").id).toBe("preview")
    expect(toolById("preview").label).toBe("Preview")
  })

  it("treats the analysis belt as analysis tools", () => {
    expect(isAnalysisTool("open-water")).toBe(true)
    expect(isAnalysisTool("dark-sea-anomaly")).toBe(true)
    expect(isAnalysisTool("catalog")).toBe(false)
  })

  it("keeps a measurement group closed until it is opened", () => {
    expect(isGroupOpen("Surface", null, [])).toBe(false)
    expect(isGroupOpen("Surface", null, ["Surface"])).toBe(true)
    expect(isGroupOpen("Objects", null, ["Surface"])).toBe(false)
  })

  it("describes the report as a full report of this scene", () => {
    const report = SHELL_TOOLS.find((tool) => tool.id === "report")

    expect(report?.description).toMatch(/full report of this scene/i)
    expect(report?.description.toLowerCase()).not.toContain("question")
  })

  it("keeps the selected tool's group open", () => {
    expect(isGroupOpen("Surface", "open-water", [])).toBe(true)
    expect(isGroupOpen("Objects", "open-water", [])).toBe(false)
    expect(isGroupOpen("Surface", "catalog", [])).toBe(false)
  })
})
