/**
 * Decide whether a catalog row can pair with the scene on stage.
 *
 * The rule matches the belt: same orbit string, same look string,
 * incidence within 1 degree, and an intersection of at least 30 percent
 * of the smaller footprint. A row that is still missing one of those
 * fields is unknown, so the download stays available.
 */

import type { BoundingBox } from "@/types"

/** One degree. A wider incidence gap would look like a brightness change. */
const INCIDENCE_TOLERANCE_DEG = 1
/** Intersection area divided by the smaller footprint. */
const MIN_OVERLAP = 0.3

export const PAIR_LOCK_WARNING =
  "This scene does not share orbit, look side, incidence within 1 degree, and footprint overlap with the open scene. A change or stack tool will stay locked."

export const COMPARISON_UNKNOWN = "This comparison is not known yet."

export interface CollectGeometry {
  orbit: string
  look: string
  incidence: number
  bbox: BoundingBox
}

export interface OpenSceneGeometry {
  orbit_state: string
  look: string
  incidence_angle: number
  bbox: BoundingBox
}

export interface CatalogGeometry {
  orbit: string | null
  look: string | null
  incidence_angle: number | null
  bbox: BoundingBox | null
}

/** True when two complete collects are close enough for change or a stack. */
export function collectsCanPair(
  left: CollectGeometry,
  right: CollectGeometry
): boolean {
  if (!left.orbit || !right.orbit || left.orbit !== right.orbit) {
    return false
  }

  if (!left.look || !right.look || left.look !== right.look) {
    return false
  }

  if (Math.abs(left.incidence - right.incidence) > INCIDENCE_TOLERANCE_DEG) {
    return false
  }

  return overlapFraction(left.bbox, right.bbox) >= MIN_OVERLAP
}

/**
 * Sentence to show above Download, or null when the row can pair.
 * An incomplete row or an incomplete open scene is unknown, not a lock.
 */
export function pairWarning(
  open: OpenSceneGeometry | null,
  row: CatalogGeometry
): string | null {
  const openGeometry = knownOpen(open)
  const rowGeometry = knownRow(row)

  if (openGeometry === null || rowGeometry === null) {
    return COMPARISON_UNKNOWN
  }

  if (collectsCanPair(openGeometry, rowGeometry)) {
    return null
  }

  return PAIR_LOCK_WARNING
}

function knownOpen(open: OpenSceneGeometry | null): CollectGeometry | null {
  if (open === null || !open.orbit_state || !open.look) {
    return null
  }

  if (!Number.isFinite(open.incidence_angle) || !knownBbox(open.bbox)) {
    return null
  }

  return {
    orbit: open.orbit_state,
    look: open.look,
    incidence: open.incidence_angle,
    bbox: open.bbox,
  }
}

function knownRow(row: CatalogGeometry): CollectGeometry | null {
  if (!row.orbit || !row.look) {
    return null
  }

  if (row.incidence_angle === null || !Number.isFinite(row.incidence_angle)) {
    return null
  }

  if (!knownBbox(row.bbox)) {
    return null
  }

  return {
    orbit: row.orbit,
    look: row.look,
    incidence: row.incidence_angle,
    bbox: row.bbox,
  }
}

function knownBbox(bbox: BoundingBox | null): bbox is BoundingBox {
  return (
    bbox !== null &&
    bbox.length === 4 &&
    bbox.every((value) => Number.isFinite(value))
  )
}

function overlapFraction(left: BoundingBox, right: BoundingBox): number {
  const west = Math.max(left[0], right[0])
  const south = Math.max(left[1], right[1])
  const east = Math.min(left[2], right[2])
  const north = Math.min(left[3], right[3])

  if (east <= west || north <= south) {
    return 0
  }

  const shared = (east - west) * (north - south)
  const leftArea = Math.max((left[2] - left[0]) * (left[3] - left[1]), 1e-12)
  const rightArea = Math.max(
    (right[2] - right[0]) * (right[3] - right[1]),
    1e-12
  )
  return shared / Math.min(leftArea, rightArea)
}
