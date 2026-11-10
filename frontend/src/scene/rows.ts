import type { Measurement } from "@/types"

export interface ReturnRow {
  id: string
  motion: string
  areaM2: number | null
  speedMS: number | null
  displacementM: number | null
  peakSigma0Db: number | null
}

type ReturnSource = {
  motion?: string | null
  area_m2?: number | null
  speed_m_s?: number | null
  displacement_m?: number | null
  peak_sigma0_db?: number | null
}

export function measurementToReturnRows(measurement: Measurement): ReturnRow[] {
  const returns = (measurement.returns ?? []) as ReturnSource[]

  return returns.map((brightReturn, index) => ({
    id: `bright-return-${index + 1}`,
    motion: brightReturn.motion?.trim() || "not reported",
    areaM2: finiteOrNull(brightReturn.area_m2),
    speedMS: finiteOrNull(brightReturn.speed_m_s),
    displacementM: finiteOrNull(brightReturn.displacement_m),
    peakSigma0Db: finiteOrNull(brightReturn.peak_sigma0_db),
  }))
}

function finiteOrNull(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}
