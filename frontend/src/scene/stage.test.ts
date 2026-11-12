import { analysisRunDisabled, stageFor } from "@/scene/stage"
import type { JobResult, SceneResponse } from "@/types"

const SCENE: SceneResponse = {
  scene_id: "ICEYE_TEST",
  collected_at: "2026-02-11T00:00:00Z",
  start_at: "2026-02-11T00:00:00Z",
  end_at: "2026-02-11T00:00:10Z",
  platform: "ICEYE-X1",
  mode: "spotlight",
  band: "X",
  polarizations: ["VV"],
  orbit_state: "ascending",
  look: "right",
  incidence_angle: 26,
  bbox: [-16.9, 28, -16.6, 28.3],
  preview_url: "/api/scenes/ICEYE_TEST/quicklook.png",
  thumbnail_url: null,
  video_url: null,
  assets_on_disk: ["qlk-cog"],
  is_test_scene: false,
  placeholder: false,
  placeholder_note: null,
  measurement: null,
  briefing_html: null,
  overview_url: "/overview.png",
}

describe("stage", () => {
  it("stays on the quicklook until this tool has an analysis picture", () => {
    const lisbon: JobResult = {
      measurement: null,
      briefing_html: null,
      overview_url: "/overview.png",
    }
    const waiting = stageFor("open-water", "quicklook", SCENE, false, lisbon)
    expect(waiting.src).toBe(SCENE.preview_url)
    expect(waiting.label).toBe("Quicklook · 11 Feb 2026, 00:00:00 UTC")
    expect(waiting.showSources).toBe(true)

    const ready = stageFor("open-water", "quicklook", SCENE, false, {
      ...lisbon,
      overview_url: "/api/scenes/ICEYE_TEST/analysis/open-water/overview.png",
    })
    expect(ready.src).toBe(
      "/api/scenes/ICEYE_TEST/analysis/open-water/overview.png"
    )
    expect(ready.label).toContain("Analysis picture")
    expect(ready.showSources).toBe(false)
  })

  it("says the library is opening when no scene is on stage yet", () => {
    const opening = stageFor(
      "preview",
      "quicklook",
      null,
      false,
      {
        measurement: null,
        briefing_html: null,
        overview_url: null,
      },
      true
    )
    expect(opening.emptyMessage).toBe("Opening the library.")
    expect(opening.showSources).toBe(false)

    const empty = stageFor("preview", "quicklook", null, false, {
      measurement: null,
      briefing_html: null,
      overview_url: null,
    })
    expect(empty.emptyMessage).toBe(
      "Select a downloaded scene from the library."
    )
  })

  it("does not put another tool's picture on the stage", () => {
    const stage = stageFor("catalog", "quicklook", SCENE, false, {
      measurement: null,
      briefing_html: null,
      overview_url: "/api/scenes/ICEYE_TEST/analysis/open-water/overview.png",
    })
    expect(stage.src).toBe(SCENE.preview_url)
  })

  it("keeps a locked tool from running", () => {
    expect(analysisRunDisabled(null)).toBe(true)
    expect(analysisRunDisabled({ locked: true })).toBe(true)
    expect(analysisRunDisabled({ locked: false })).toBe(false)
  })
})
