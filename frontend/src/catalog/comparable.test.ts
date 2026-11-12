import type { BoundingBox } from "@/types"

import {
  COMPARISON_UNKNOWN,
  PAIR_LOCK_WARNING,
  collectsCanPair,
  pairWarning,
  type CatalogGeometry,
  type CollectGeometry,
  type OpenSceneGeometry,
} from "@/catalog/comparable"

/** Published 25 de Abril footprint from the Lisbon STAC item. */
const LISBON_BBOX: BoundingBox = [
  -9.213969443201776, 38.65979028852499, -9.139894173828166, 38.71784777157828,
]

const LISBON: CollectGeometry = {
  orbit: "descending",
  look: "right",
  incidence: 32,
  bbox: LISBON_BBOX,
}

/** A Canary-like spotlight: ascending, right, 26°, around −17°, 28°. */
const CANARY: CollectGeometry = {
  orbit: "ascending",
  look: "right",
  incidence: 26,
  bbox: [-16.9, 28, -16.6, 28.3],
}

describe("collect pairing", () => {
  it("does not pair a Lisbon collect with a Canary collect", () => {
    expect(collectsCanPair(LISBON, CANARY)).toBe(false)
  })

  it("pairs two copies of the Lisbon geometry", () => {
    expect(collectsCanPair(LISBON, { ...LISBON })).toBe(true)
  })

  it("keeps a one-degree incidence gap and rejects a wider one", () => {
    expect(collectsCanPair(LISBON, { ...LISBON, incidence: 33 })).toBe(true)
    expect(collectsCanPair(LISBON, { ...LISBON, incidence: 33.1 })).toBe(false)
  })

  it("uses the 30 percent overlap gate", () => {
    expect(collectsCanPair(LISBON, shiftEast(LISBON, 0.8))).toBe(false)
    expect(collectsCanPair(LISBON, shiftEast(LISBON, 0.5))).toBe(true)
  })

  it("warns when the open scene can be compared and this row cannot", () => {
    expect(pairWarning(openFrom(LISBON), rowFrom(CANARY))).toBe(
      PAIR_LOCK_WARNING
    )
  })

  it("stays quiet when the row shares the open scene geometry", () => {
    expect(pairWarning(openFrom(LISBON), rowFrom(LISBON))).toBeNull()
  })

  it("says the comparison is not known when the row has no footprint yet", () => {
    expect(
      pairWarning(openFrom(LISBON), { ...rowFrom(CANARY), bbox: null })
    ).toBe(COMPARISON_UNKNOWN)
    expect(
      pairWarning(openFrom(LISBON), { ...rowFrom(LISBON), look: "" })
    ).toBe(COMPARISON_UNKNOWN)
    expect(
      pairWarning(openFrom(LISBON), {
        ...rowFrom(LISBON),
        incidence_angle: null,
      })
    ).toBe(COMPARISON_UNKNOWN)
    expect(pairWarning(null, rowFrom(LISBON))).toBe(COMPARISON_UNKNOWN)
  })
})

function openFrom(collect: CollectGeometry): OpenSceneGeometry {
  return {
    orbit_state: collect.orbit,
    look: collect.look,
    incidence_angle: collect.incidence,
    bbox: collect.bbox,
  }
}

function rowFrom(collect: CollectGeometry): CatalogGeometry {
  return {
    orbit: collect.orbit,
    look: collect.look,
    incidence_angle: collect.incidence,
    bbox: collect.bbox,
  }
}

/** Slide a copy east by a fraction of its width. Equal boxes then overlap by the rest. */
function shiftEast(
  collect: CollectGeometry,
  fractionOfWidth: number
): CollectGeometry {
  const [west, south, east, north] = collect.bbox
  const shift = (east - west) * fractionOfWidth
  return {
    ...collect,
    bbox: [west + shift, south, east + shift, north],
  }
}
