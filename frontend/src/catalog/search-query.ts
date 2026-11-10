/**
 * Build the catalog search URL. A footprint is sent only when all four
 * edges are numbers, because the server treats a partial bbox as an error.
 */

export interface CatalogFilters {
  q: string
  start: string
  end: string
  satellite: string
  product: string
  west: string
  south: string
  east: string
  north: string
  offset: number
}

export const EMPTY_FILTERS: CatalogFilters = {
  q: "",
  start: "",
  end: "",
  satellite: "",
  product: "",
  west: "",
  south: "",
  east: "",
  north: "",
  offset: 0,
}

const PAGE_SIZE = 24

export function catalogSearchPath(filters: CatalogFilters): string {
  const params = new URLSearchParams()
  const query = filters.q.trim()

  if (query) {
    params.set("q", query)
  }

  if (filters.start) {
    params.set("start", filters.start)
  }

  if (filters.end) {
    params.set("end", filters.end)
  }

  if (filters.satellite) {
    params.set("satellite", filters.satellite)
  }

  if (filters.product) {
    params.set("product", filters.product)
  }

  const edges = [filters.west, filters.south, filters.east, filters.north]
  const numbers = edges.map((edge) => edge.trim())

  if (numbers.every((edge) => edge !== "" && Number.isFinite(Number(edge)))) {
    params.set("bbox", numbers.join(","))
  }

  params.set("limit", String(PAGE_SIZE))
  params.set("offset", String(Math.max(0, filters.offset)))
  return `/api/catalog/search?${params.toString()}`
}
