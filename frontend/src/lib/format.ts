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

export function formatFootprintSize(bbox: BoundingBox): string {
  const [west, south, east, north] = bbox
  const mid = ((south + north) / 2) * (Math.PI / 180)
  const height = Math.abs(north - south) * 111
  const width = Math.abs(east - west) * 111 * Math.cos(mid)

  return `${Math.round(width)} × ${Math.round(height)} km`
}

export function catalogSummary(item: {
  acquired_at: string | null
  satellite: string | null
  mode: string | null
  product_code: string | null
  incidence_angle: number | null
  bbox: BoundingBox | null
  orbit: string | null
  look: string | null
  has_grd: boolean
  has_slc: boolean
  has_video: boolean
}): string {
  const assets = [
    item.has_grd ? "GRD" : null,
    item.has_slc ? "SLC" : null,
    item.has_video ? "video" : null,
  ]
  const incidence =
    typeof item.incidence_angle === "number" &&
    Number.isFinite(item.incidence_angle)
      ? `${item.incidence_angle.toFixed(1)}°`
      : null

  return [
    item.acquired_at,
    item.satellite,
    item.mode ?? item.product_code,
    item.bbox ? formatFootprintSize(item.bbox) : null,
    incidence,
    item.orbit,
    item.look,
    assets.filter(Boolean).join(", ") || null,
  ]
    .filter(Boolean)
    .join(" · ")
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

const HEADER_FACT_LABELS = [
  "Collected",
  "Platform",
  "Mode",
  "Band",
  "Polarization",
] as const

/** One line for the shell header: time, platform, mode, band, polarization. */
export function headerFactLine(scene: SceneResponse): string {
  const facts = collectFacts(scene)

  return HEADER_FACT_LABELS.map(
    (label) => facts.find((fact) => fact.label === label)?.value ?? ""
  )
    .filter((value) => value.length > 0)
    .join(" · ")
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
      value: `${scene.incidence_angle.toFixed(1)}°`,
    },
    { label: "Bounding box", value: formatBbox(scene.bbox) },
  ]
}

function formatCoordinate(value: number): string {
  return value.toFixed(3)
}
