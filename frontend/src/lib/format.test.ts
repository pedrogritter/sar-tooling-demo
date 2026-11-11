import type { SceneResponse } from "@/types"

import {
  collectFacts,
  formatBbox,
  formatFootprintSize,
  formatMeasure,
  formatPercent,
  formatUtc,
  measurementNumber,
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
    expect(formatFootprintSize([-16.95, 28.0, -16.45, 28.5])).toBe(
      "49 × 56 km"
    )
  })

  it("prints a measurement with its unit", () => {
    expect(formatMeasure(9.73, "km2")).toBe("9.73 km2")
    expect(formatMeasure(27.8, "dB")).toBe("27.80 dB")
    expect(formatMeasure(3, "px")).toBe("3 px")
    expect(formatMeasure(Number.POSITIVE_INFINITY, "m")).toBe("not reported")
    expect(formatMeasure(undefined, "m")).toBe("not reported")
  })

  it("prints a water fraction as a percent", () => {
    expect(formatPercent(0.391)).toBe("39.1%")
    expect(formatPercent(null)).toBe("not reported")
  })

  it("reads only finite measurement numbers", () => {
    expect(measurementNumber({ water_km2: 9.73 }, "water_km2")).toBe(9.73)
    expect(measurementNumber({ water_km2: Number.NaN }, "water_km2")).toBeNull()
    expect(measurementNumber({}, "missing")).toBeNull()
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
      "31.2 deg"
    )
    expect(facts.find((fact) => fact.label === "Bounding box")?.value).toBe(
      "-9.214, 38.660, -9.140, 38.718"
    )
  })

  it("says polarization is not reported when the list is empty", () => {
    const facts = collectFacts({ ...scene, polarizations: [] })
    expect(facts.find((fact) => fact.label === "Polarization")?.value).toBe(
      "not reported"
    )
  })
})
