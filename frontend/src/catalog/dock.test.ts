import { dockCanOpen } from "@/catalog/dock"

describe("download dock", () => {
  it("offers Open when the download is a different scene", () => {
    expect(dockCanOpen("ICEYE_OTHER", "ICEYE_OPEN")).toBe(true)
    expect(dockCanOpen("ICEYE_OTHER", null)).toBe(true)
  })

  it("hides Open when that scene is already on stage", () => {
    expect(dockCanOpen("ICEYE_OPEN", "ICEYE_OPEN")).toBe(false)
    expect(dockCanOpen(null, "ICEYE_OPEN")).toBe(false)
    expect(dockCanOpen(null, null)).toBe(false)
  })
})
