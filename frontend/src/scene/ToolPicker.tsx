import { Image, Ruler } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { TOOLS, type ToolId } from "@/scene/tools"

const ICONS: Record<ToolId, LucideIcon> = {
  preview: Image,
  measure: Ruler,
}

interface ToolPickerProps {
  selected: ToolId
  onSelect: (tool: ToolId) => void
}

export function ToolPicker({ selected, onSelect }: ToolPickerProps) {
  return (
    <nav
      aria-label="Tools"
      className="flex shrink-0 gap-1 overflow-x-auto border-b bg-background p-2 md:w-[4.75rem] md:flex-col md:overflow-visible md:border-r md:border-b-0"
    >
      <p className="hidden px-1 pb-1 text-[0.62rem] font-medium tracking-[0.14em] text-muted-foreground uppercase md:block">
        Tools
      </p>
      {TOOLS.map((tool) => {
        const Icon = ICONS[tool.id]
        const active = tool.id === selected

        return (
          <Button
            key={tool.id}
            type="button"
            variant={active ? "secondary" : "ghost"}
            aria-pressed={active}
            className="h-auto min-w-16 flex-1 flex-col gap-1 px-1 py-2 text-[0.65rem] md:w-full md:flex-none"
            onClick={() => {
              onSelect(tool.id)
            }}
          >
            <Icon />
            {tool.label}
          </Button>
        )
      })}
    </nav>
  )
}
