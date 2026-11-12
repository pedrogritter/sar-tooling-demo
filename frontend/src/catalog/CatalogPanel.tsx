import { useEffect, useState } from "react"

import {
  fetchCatalog,
  fetchCatalogItem,
  refreshCatalog,
  startDownload,
} from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  catalogSearchPath,
  EMPTY_FILTERS,
  type CatalogFilters,
} from "@/catalog/search-query"
import { catalogSummary, formatBytes } from "@/lib/format"
import type { CatalogItemDetail, CatalogSearchResponse } from "@/types"

interface CatalogPanelProps {
  onOpenScene: (sceneId: string) => void
  onDownloadStarted: () => void
}

/**
 * Search the open-data collection. Rows appear from the link list first.
 * Thumbnails and footprints fill in as the server caches each item JSON.
 */
export function CatalogPanel({
  onOpenScene,
  onDownloadStarted,
}: CatalogPanelProps) {
  const [filters, setFilters] = useState<CatalogFilters>(EMPTY_FILTERS)
  const [result, setResult] = useState<CatalogSearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<CatalogItemDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [checked, setChecked] = useState<string[]>([])
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const next = await fetchCatalog(catalogSearchPath(filters))

        if (!active) {
          return
        }

        setResult(next)
        setError(null)

        if (next.indexing) {
          window.setTimeout(() => {
            if (active) {
              void load()
            }
          }, 2000)
        }
      } catch (caught) {
        if (active) {
          setError(messageFrom(caught))
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => {
      active = false
    }
  }, [filters])

  function change(patch: Partial<CatalogFilters>) {
    setLoading(true)
    setFilters((current) => ({
      ...current,
      ...patch,
      offset: patch.offset ?? 0,
    }))
  }

  async function openDetail(sceneId: string) {
    setDetail(null)
    setDetailError(null)
    setDownloadError(null)

    try {
      const next = await fetchCatalogItem(sceneId)
      setDetail(next)
      setChecked(
        next.assets
          .filter((asset) => asset.preview_default)
          .map((asset) => asset.key)
      )
    } catch (caught) {
      setDetailError(messageFrom(caught))
    }
  }

  async function download() {
    if (!detail || checked.length === 0) {
      return
    }

    setDownloading(true)
    setDownloadError(null)

    try {
      await startDownload(detail.scene_id, checked)
      onDownloadStarted()
    } catch (caught) {
      setDownloadError(messageFrom(caught))
    } finally {
      setDownloading(false)
    }
  }

  const page = result ? Math.floor(result.offset / result.limit) + 1 : 1
  const pages = result ? Math.max(1, Math.ceil(result.total / result.limit)) : 1

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ScrollArea className="flex-1">
        <form
          className="flex flex-col gap-3 p-3"
          onSubmit={(event) => {
            event.preventDefault()
          }}
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-medium">Catalog</h2>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={() => {
                setLoading(true)
                void refreshCatalog().then(() => {
                  setFilters((current) => ({ ...current }))
                })
              }}
            >
              Refresh
            </Button>
          </div>
          <Input
            aria-label="Scene id"
            placeholder="Scene id"
            value={filters.q}
            onValueChange={(value) => {
              change({ q: value })
            }}
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              aria-label="Start date"
              type="date"
              value={filters.start}
              onValueChange={(value) => {
                change({ start: value })
              }}
            />
            <Input
              aria-label="End date"
              type="date"
              value={filters.end}
              onValueChange={(value) => {
                change({ end: value })
              }}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Select
              label="Satellite"
              value={filters.satellite}
              options={result?.satellites ?? []}
              onChange={(satellite) => {
                change({ satellite })
              }}
            />
            <Select
              label="Product"
              value={filters.product}
              options={result?.products ?? []}
              onChange={(product) => {
                change({ product })
              }}
            />
          </div>
          <fieldset className="grid grid-cols-4 gap-1">
            <legend className="col-span-4 mb-1 text-xs text-muted-foreground">
              Footprint, west south east north
            </legend>
            {(["west", "south", "east", "north"] as const).map((edge) => (
              <Input
                key={edge}
                aria-label={edge}
                inputMode="decimal"
                value={filters[edge]}
                onValueChange={(value) => {
                  change({ [edge]: value })
                }}
              />
            ))}
          </fieldset>
          <p className="text-xs text-muted-foreground" role="status">
            {statusLine(result, loading, error)}
          </p>
        </form>

        <ul className="flex flex-col gap-2 px-3 pb-3">
          {result?.items.map((item) => (
            <li key={item.scene_id}>
              <button
                type="button"
                className="flex w-full gap-2 rounded-lg border p-2 text-left hover:bg-muted"
                onClick={() => {
                  void openDetail(item.scene_id)
                }}
              >
                {item.thumbnail_url ? (
                  <img
                    className="size-14 shrink-0 bg-neutral-950 object-contain"
                    src={item.thumbnail_url}
                    alt=""
                  />
                ) : (
                  <span className="size-14 shrink-0 bg-neutral-950" />
                )}
                <span className="min-w-0">
                  {item.place ? (
                    <span className="block truncate text-sm">{item.place}</span>
                  ) : null}
                  <span className="block truncate font-mono text-[0.65rem] text-muted-foreground">
                    {item.scene_id}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {catalogSummary(item)}
                  </span>
                  {item.on_disk ? (
                    <Badge variant="secondary" className="mt-1">
                      On disk
                    </Badge>
                  ) : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </ScrollArea>

      <div className="flex items-center justify-between gap-2 border-t px-3 py-2">
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={!result || result.offset <= 0}
          onClick={() => {
            change({
              offset: Math.max(0, filters.offset - (result?.limit ?? 24)),
            })
          }}
        >
          Previous
        </Button>
        <span className="text-xs text-muted-foreground tabular-nums">
          {page} / {pages}
        </span>
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={!result || result.offset + result.limit >= result.total}
          onClick={() => {
            change({ offset: filters.offset + (result?.limit ?? 24) })
          }}
        >
          Next
        </Button>
      </div>

      {detail || detailError ? (
        <div className="flex max-h-[45%] flex-col gap-2 border-t p-3">
          <ScrollArea className="min-h-0 flex-1">
            {detailError ? (
              <p className="text-sm text-destructive">{detailError}</p>
            ) : null}
            {detail ? (
              <div className="flex flex-col gap-2">
                {detail.place ? (
                  <p className="text-sm">{detail.place}</p>
                ) : null}
                <p className="font-mono text-[0.65rem] break-all text-muted-foreground">
                  {detail.scene_id}
                </p>
                <p className="text-xs text-muted-foreground">
                  {catalogSummary(detail)}
                </p>
                {detail.assets.map((asset) => (
                  <label
                    key={asset.key}
                    className="flex items-start gap-2 text-sm"
                  >
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={checked.includes(asset.key)}
                      onChange={(event) => {
                        const selected = event.currentTarget.checked
                        setChecked((current) =>
                          selected
                            ? [...current, asset.key]
                            : current.filter((key) => key !== asset.key)
                        )
                      }}
                    />
                    <span>
                      <span className="block">{asset.title}</span>
                      <span className="text-xs text-muted-foreground">
                        {asset.key}
                        {asset.large ? " · large" : ""} ·{" "}
                        {formatBytes(asset.bytes)}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            ) : null}
          </ScrollArea>
          {downloadError ? (
            <p className="text-sm text-destructive">{downloadError}</p>
          ) : null}
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              disabled={!detail || checked.length === 0 || downloading}
              onClick={() => {
                void download()
              }}
            >
              {downloading ? "Starting" : "Download"}
            </Button>
            {detail?.on_disk ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  onOpenScene(detail.scene_id)
                }}
              >
                Open
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  return (
    <select
      aria-label={label}
      className="h-8 rounded-lg border border-input bg-background px-2 text-sm text-foreground scheme-light"
      value={value}
      onChange={(event) => {
        onChange(event.currentTarget.value)
      }}
    >
      <option value="">{label}</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  )
}

function statusLine(
  result: CatalogSearchResponse | null,
  loading: boolean,
  error: string | null
): string {
  if (error) {
    return error
  }

  if (!result) {
    return loading ? "Reading the collection…" : ""
  }

  const index = result.indexing
    ? `Reading item records ${result.indexed} of ${result.record_count}.`
    : `${result.indexed} of ${result.record_count} records cached.`
  const unread =
    result.unread_for_bbox > 0
      ? ` ${result.unread_for_bbox} matches still have no footprint.`
      : ""
  return `${result.total} matches. ${index}${unread}`
}

function messageFrom(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message
  }

  return "The catalog request failed."
}
