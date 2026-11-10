import { isAnalysisTool, selectTool, toolById } from "@/scene/tools"

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
})
