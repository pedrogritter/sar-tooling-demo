import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { formatUtc } from "@/lib/format"
import type { LibraryScene } from "@/types"

interface LibraryPanelProps {
  scenes: LibraryScene[]
  loading: boolean
  error: string | null
  selectedId: string | null
  onSelect: (sceneId: string) => void
  onRefresh: () => void
}

/** Scenes whose STAC item is already in data/scenes. */
export function LibraryPanel({
  scenes,
  loading,
  error,
  selectedId,
  onSelect,
  onRefresh,
}: LibraryPanelProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-3">
        <h2 className="text-sm font-medium">Library</h2>
        <Button type="button" variant="ghost" size="xs" onClick={onRefresh}>
          Refresh
        </Button>
      </div>
      <ScrollArea className="flex-1 px-3 pb-3">
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        {loading && scenes.length === 0 ? (
          <p className="text-sm text-muted-foreground">Reading downloaded scenes…</p>
        ) : null}
        {!loading && scenes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No scene is on disk yet. Download one from the catalog.
          </p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {scenes.map((scene) => (
            <li key={scene.scene_id}>
              <button
                type="button"
                aria-pressed={selectedId === scene.scene_id}
                className="flex w-full flex-col gap-1 rounded-lg border p-2 text-left hover:bg-muted aria-pressed:bg-muted"
                onClick={() => {
                  onSelect(scene.scene_id)
                }}
              >
                <span className="flex flex-wrap items-center gap-1">
                  {scene.is_test_scene ? <Badge>Test scene</Badge> : null}
                  <Badge variant="outline">{scene.mode}</Badge>
                </span>
                <span className="font-mono text-[0.65rem] break-all">
                  {scene.scene_id}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatUtc(scene.collected_at)} · {scene.platform}
                </span>
                <span className="text-xs text-muted-foreground">
                  {scene.assets_on_disk.join(", ") || "STAC record only"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </ScrollArea>
    </div>
  )
}
