import type { BoundingBox, Measurement, SceneResponse } from "@/types"

const FRACTION_DIGITS: Record<string, number> = {
  dB: 2,
  km2: 2,
  m: 1,
  m2: 1,
  "m/s": 2,
}

export interface Fact {
  label: string
  value: string
}

export function formatUtc(value: string): string {
  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short",
  })
    .format(date)
    .replace(" at ", ", ")
}

export function formatBbox([west, south, east, north]: BoundingBox): string {
  return `${formatCoordinate(west)}, ${formatCoordinate(south)}, ${formatCoordinate(east)}, ${formatCoordinate(north)}`
}

export function formatMeasure(
  value: number | null | undefined,
  unit: string
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "not reported"
  }

  const digits = FRACTION_DIGITS[unit] ?? 1
  const formatted = new Intl.NumberFormat("en", {
    maximumFractionDigits: digits,
    minimumFractionDigits: unit === "dB" ? 2 : 0,
  }).format(value)

  return `${formatted} ${unit}`
}

export function formatBytes(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return "size unknown"
  }

  if (value < 1000) {
    return `${Math.round(value)} B`
  }

  if (value < 1_000_000) {
    return `${(value / 1000).toFixed(0)} kB`
  }

  if (value < 1_000_000_000) {
    return `${(value / 1_000_000).toFixed(1)} MB`
  }

  return `${(value / 1_000_000_000).toFixed(2)} GB`
}

export function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "not reported"
  }

  return new Intl.NumberFormat("en", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value)
}

export function measurementNumber(
  measurement: Measurement,
  key: string
): number | null {
  const value = measurement[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export function collectFacts(scene: SceneResponse): Fact[] {
  const polarization =
    scene.polarizations.length > 0
      ? scene.polarizations.join(", ")
      : "not reported"

  return [
    { label: "Scene", value: scene.scene_id },
    { label: "Collected", value: formatUtc(scene.collected_at) },
    {
      label: "Window",
      value: `${formatUtc(scene.start_at)} – ${formatUtc(scene.end_at)}`,
    },
    { label: "Platform", value: scene.platform },
    { label: "Mode", value: scene.mode },
    { label: "Band", value: scene.band },
    { label: "Polarization", value: polarization },
    { label: "Orbit", value: scene.orbit_state },
    {
      label: "Incidence",
      value: `${scene.incidence_angle.toFixed(1)} deg`,
    },
    { label: "Bounding box", value: formatBbox(scene.bbox) },
  ]
}

function formatCoordinate(value: number): string {
  return value.toFixed(3)
}
