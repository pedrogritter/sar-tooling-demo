import type { SceneResponse } from "@/types"

import {
  collectFacts,
  formatBbox,
  headerFactLine,
  formatFootprintSize,
  formatUtc,
} from "./format"

const scene = {
  scene_id: "ICEYE_TEST",
  collected_at: "2025-10-24T13:53:09Z",
  start_at: "2025-10-24T13:53:00Z",
  end_at: "2025-10-24T13:53:25Z",
  platform: "ICEYE-X52",
  mode: "SPOTLIGHT",
  band: "X",
  polarizations: ["VV"],
  orbit_state: "ascending",
  incidence_angle: 31.24,
  bbox: [-9.214, 38.66, -9.14, 38.718],
  preview_url: "/quicklook.png",
  measurement: null,
  briefing_html: null,
  overview_url: null,
} as SceneResponse

describe("formatters", () => {
  it("prints a UTC timestamp", () => {
    expect(formatUtc("2025-10-24T13:53:09Z")).toBe("24 Oct 2025, 13:53:09 UTC")
  })

  it("leaves an unparseable timestamp unchanged", () => {
    expect(formatUtc("not-a-date")).toBe("not-a-date")
  })

  it("prints the bounding box to three decimals", () => {
    expect(formatBbox([-9.21412, 38.66, -9.14, 38.7184])).toBe(
      "-9.214, 38.660, -9.140, 38.718"
    )
  })

  it("prints a footprint size in kilometres", () => {
    expect(formatFootprintSize([-16.95, 28.0, -16.45, 28.5])).toBe("49 × 56 km")
  })

  it("lists the collect facts for a scene", () => {
    const facts = collectFacts(scene)
    expect(facts.find((fact) => fact.label === "Platform")?.value).toBe(
      "ICEYE-X52"
    )
    expect(facts.find((fact) => fact.label === "Polarization")?.value).toBe(
      "VV"
    )
    expect(facts.find((fact) => fact.label === "Incidence")?.value).toBe(
      "31.2°"
    )
    expect(facts.find((fact) => fact.label === "Bounding box")?.value).toBe(
      "-9.214, 38.660, -9.140, 38.718"
    )
  })

  it("puts the compact facts on one header line", () => {
    expect(headerFactLine(scene)).toBe(
      "24 Oct 2025, 13:53:09 UTC · ICEYE-X52 · SPOTLIGHT · X · VV"
    )
  })

  it("says polarization is not reported when the list is empty", () => {
    const facts = collectFacts({ ...scene, polarizations: [] })
    expect(facts.find((fact) => fact.label === "Polarization")?.value).toBe(
      "not reported"
    )
  })
})
