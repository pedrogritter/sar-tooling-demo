import { closeLast, toggleLeft, toggleRight, type EdgeState } from "@/workspace/edges"
import { catalogSearchPath, type CatalogFilters } from "@/catalog/search-query"

describe("edge panels", () => {
  const closed: EdgeState = { left: null, right: null, last: null }

  it("opens a tool and closes it when the same tool is chosen again", () => {
    const open = toggleLeft(closed, "catalog")
    expect(open.left).toBe("catalog")
    expect(open.last).toBe("left")
    expect(toggleLeft(open, "catalog").left).toBeNull()
  })

  it("replaces the panel on the same edge and leaves the other edge", () => {
    const both = toggleRight(toggleLeft(closed, "library"), "measure")
    const next = toggleLeft(both, "facts")
    expect(next.left).toBe("facts")
    expect(next.right).toBe("measure")
    expect(closeLast(next).right).toBe("measure")
    expect(closeLast(next).left).toBeNull()
  })
})

describe("catalog search path", () => {
  const filters: CatalogFilters = {
    q: "  lisbon ",
    start: "2025-10-01",
    end: "",
    satellite: "X52",
    product: "",
    west: "",
    south: "",
    east: "",
    north: "",
    offset: 24,
  }

  it("omits empty filters and a partial footprint", () => {
    const path = catalogSearchPath({ ...filters, west: "1", south: "2" })
    const params = new URLSearchParams(path.split("?")[1])
    expect(params.get("q")).toBe("lisbon")
    expect(params.get("start")).toBe("2025-10-01")
    expect(params.get("satellite")).toBe("X52")
    expect(params.get("bbox")).toBeNull()
    expect(params.get("offset")).toBe("24")
    expect(params.get("limit")).toBe("24")
  })

  it("sends a footprint only when all four edges are numbers", () => {
    const path = catalogSearchPath({
      ...filters,
      west: "-10",
      south: "38",
      east: "-9",
      north: "39",
    })
    const params = new URLSearchParams(path.split("?")[1])
    expect(params.get("bbox")).toBe("-10,38,-9,39")
  })
})
