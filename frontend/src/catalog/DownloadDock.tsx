import { dockCanOpen } from "@/catalog/dock"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { formatBytes } from "@/lib/format"
import type { DownloadSnapshot } from "@/types"

interface DownloadDockProps {
  snapshot: DownloadSnapshot | null
  expanded: boolean
  openSceneId: string | null
  onToggle: () => void
  onDismiss: () => void
  onOpen: (sceneId: string) => void
}

/**
 * Bottom status for the one active download. Byte counts are the size of
 * the file being written, polled with the job.
 */
export function DownloadDock({
  snapshot,
  expanded,
  openSceneId,
  onToggle,
  onDismiss,
  onOpen,
}: DownloadDockProps) {
  if (!snapshot || snapshot.status === "idle" || !snapshot.scene_id) {
    return null
  }

  const active =
    snapshot.files.find((file) => file.state === "downloading") ??
    snapshot.files.find((file) => file.state === "pending")
  const doneBytes = snapshot.files.reduce(
    (sum, file) => sum + file.bytes_done,
    0
  )
  const totalBytes = snapshot.files.reduce(
    (sum, file) => sum + file.bytes_total,
    0
  )
  const percent =
    totalBytes > 0
      ? Math.min(100, Math.round((doneBytes / totalBytes) * 100))
      : 0

  return (
    <section aria-label="Download" className="shrink-0 border-t bg-background">
      <div className="flex items-center gap-3 px-3 py-2">
        <button
          type="button"
          className="min-w-0 flex-1 rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          <span className="block truncate text-xs">
            {headline(snapshot, active?.name ?? "")}
          </span>
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {snapshot.scene_id}
            {active
              ? ` · ${formatBytes(active.bytes_done)} / ${formatBytes(active.bytes_total)}`
              : ""}
          </span>
        </button>
        {dockCanOpen(snapshot.scene_id, openSceneId) ? (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => {
              if (snapshot.scene_id) {
                onOpen(snapshot.scene_id)
              }
            }}
          >
            Open
          </Button>
        ) : null}
        <div className="hidden w-40 sm:block">
          <Progress value={percent} />
        </div>
        {snapshot.status !== "running" ? (
          <Button type="button" variant="ghost" size="xs" onClick={onDismiss}>
            Dismiss
          </Button>
        ) : null}
      </div>
      {expanded ? (
        <ul className="flex flex-col gap-2 border-t px-3 py-2">
          {snapshot.files.map((file) => {
            const filePercent =
              file.bytes_total > 0
                ? Math.min(
                    100,
                    Math.round((file.bytes_done / file.bytes_total) * 100)
                  )
                : 0

            return (
              <li key={file.name} className="flex flex-col gap-1">
                <div className="flex justify-between gap-3 text-xs">
                  <span className="truncate font-mono">{file.name}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {file.state} · {formatBytes(file.bytes_done)}
                    {file.bytes_total > 0
                      ? ` / ${formatBytes(file.bytes_total)}`
                      : ""}
                  </span>
                </div>
                <Progress value={filePercent} />
              </li>
            )
          })}
          {snapshot.error ? (
            <li className="text-sm text-destructive">{snapshot.error}</li>
          ) : null}
        </ul>
      ) : null}
    </section>
  )
}

function headline(snapshot: DownloadSnapshot, name: string): string {
  if (snapshot.status === "failed") {
    return "Download failed"
  }

  if (snapshot.status === "done") {
    return "Download finished"
  }

  return name ? `Downloading ${name}` : "Downloading"
}
