import type { Measurement } from "@/types"

import { measurementToReturnRows } from "./rows"

const fixture = {
  water_km2: 9.73,
  returns: [
    {
      kind: "bright return at the waterline",
      area_m2: 151.2,
      peak_sigma0_db: 10.92,
      motion: "moved",
      displacement_m: 10.6,
      speed_m_s: 0.74,
    },
    {
      kind: "bright return at the waterline",
      area_m2: 121.3,
      peak_sigma0_db: 25.04,
      motion: "stationary during the dwell",
      displacement_m: 0,
      speed_m_s: 0,
    },
  ],
} as Measurement

describe("measurementToReturnRows", () => {
  it("maps bright returns to display rows", () => {
    expect(measurementToReturnRows(fixture)).toEqual([
      {
        id: "bright-return-1",
        motion: "moved",
        areaM2: 151.2,
        speedMS: 0.74,
        displacementM: 10.6,
        peakSigma0Db: 10.92,
      },
      {
        id: "bright-return-2",
        motion: "stationary during the dwell",
        areaM2: 121.3,
        speedMS: 0,
        displacementM: 0,
        peakSigma0Db: 25.04,
      },
    ])
  })

  it("keeps a blank motion and a non-finite number out of the row", () => {
    const measurement = {
      returns: [{ motion: "  ", area_m2: Number.NaN, speed_m_s: null }],
    } as unknown as Measurement

    expect(measurementToReturnRows(measurement)).toEqual([
      {
        id: "bright-return-1",
        motion: "not reported",
        areaM2: null,
        speedMS: null,
        displacementM: null,
        peakSigma0Db: null,
      },
    ])
  })

  it("returns an empty list when the measurement has no returns", () => {
    expect(measurementToReturnRows({} as Measurement)).toEqual([])
  })
})
