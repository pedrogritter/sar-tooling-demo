import type { Measurement } from "@/types";

export type ReturnRow = {
  id: string;
  motion: string;
  areaM2: number | null;
  speedMS: number | null;
  peakSigma0Db: number | null;
};

type MeasurementWithReturns = Measurement & {
  returns?: Array<{
    motion?: string | null;
    area_m2?: number | null;
    speed_m_s?: number | null;
    peak_sigma0_db?: number | null;
  }>;
};

export function measurementToReturnRows(measurement: Measurement): ReturnRow[] {
  const returns = (measurement as MeasurementWithReturns).returns ?? [];

  return returns.map((brightReturn, index) => ({
    id: `bright-return-${index + 1}`,
    motion: brightReturn.motion ?? "not reported",
    areaM2: toNumberOrNull(brightReturn.area_m2),
    speedMS: toNumberOrNull(brightReturn.speed_m_s),
    peakSigma0Db: toNumberOrNull(brightReturn.peak_sigma0_db),
  }));
}

function toNumberOrNull(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
