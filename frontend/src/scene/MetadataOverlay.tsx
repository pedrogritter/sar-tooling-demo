import { useState } from "react"

import { Button } from "@/components/ui/button"
import { collectFacts } from "@/lib/format"
import { FactList } from "@/scene/FactList"
import type { SceneResponse } from "@/types"

const COMPACT_LABELS = ["Collected", "Platform", "Mode", "Band", "Polarization"]

interface MetadataOverlayProps {
  scene: SceneResponse | null
  loading: boolean
  error: string | null
  onHide: () => void
}

export function MetadataOverlay({
  scene,
  loading,
  error,
  onHide,
}: MetadataOverlayProps) {
  const [expanded, setExpanded] = useState(false)
  const facts = scene ? collectFacts(scene) : []
  const visible = expanded
    ? facts
    : facts.filter((fact) => COMPACT_LABELS.includes(fact.label))

  return (
    <aside className="absolute top-3 right-3 z-10 flex max-h-[min(24rem,70%)] w-60 flex-col gap-2 overflow-y-auto rounded-lg border bg-background/95 p-3 shadow-md backdrop-blur-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">Metadata</h2>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="px-1"
          onClick={onHide}
        >
          Hide
        </Button>
      </div>

      {loading ? (
        <p className="text-xs text-muted-foreground">Loading scene metadata.</p>
      ) : null}

      {error ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      {scene ? <FactList dense facts={visible} /> : null}

      {scene ? (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="self-start px-0"
          aria-expanded={expanded}
          onClick={() => {
            setExpanded((open) => !open)
          }}
        >
          {expanded ? "Show less" : "All fields"}
        </Button>
      ) : null}
    </aside>
  )
}
