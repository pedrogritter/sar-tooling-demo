// If this branch lacks ui/package.json, the sibling package should provide Jest, ts-jest, @types/jest, and TypeScript.
import type { Measurement } from "@/types";

import { measurementToReturnRows } from "./rows";

const fixture = {
  water_km2: 9.73,
  basins: [
    {
      area_km2: 4.94,
      median_sigma0_db: -16.69,
    },
    {
      area_km2: 4.79,
      median_sigma0_db: -17.6,
    },
  ],
  bridge: {
    kind: "bridge deck return",
    area_m2: 78129.8,
    length_m: 2313.3,
    width_m: 156.7,
    peak_sigma0_db: 27.84,
  },
  returns: [
    {
      kind: "bright return at the waterline",
      area_m2: 151.2,
      peak_sigma0_db: 10.92,
      motion: "moved",
      speed_m_s: 0.74,
    },
    {
      kind: "bright return at the waterline",
      area_m2: 121.3,
      peak_sigma0_db: 25.04,
      motion: "stationary during the dwell",
      speed_m_s: 0,
    },
  ],
} as Measurement;

describe("measurementToReturnRows", () => {
  it("maps bright returns to display rows without network data", () => {
    expect(measurementToReturnRows(fixture)).toEqual([
      {
        id: "bright-return-1",
        motion: "moved",
        areaM2: 151.2,
        speedMS: 0.74,
        peakSigma0Db: 10.92,
      },
      {
        id: "bright-return-2",
        motion: "stationary during the dwell",
        areaM2: 121.3,
        speedMS: 0,
        peakSigma0Db: 25.04,
      },
    ]);
  });
});
