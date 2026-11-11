import { FileText, FolderOpen, Image, Search } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  ANALYSIS_GROUPS,
  ANALYSIS_TOOLS,
  SHELL_TOOLS,
  type ToolId,
} from "@/scene/tools"

const ICONS: Record<(typeof SHELL_TOOLS)[number]["id"], LucideIcon> = {
  preview: Image,
  catalog: Search,
  library: FolderOpen,
  report: FileText,
}

interface ToolPickerProps {
  selected: ToolId | null
  onSelect: (tool: ToolId) => void
}

/** Tool column. Shell tools stay on top. Analysis tools are grouped. */
export function ToolPicker({ selected, onSelect }: ToolPickerProps) {
  return (
    <nav
      aria-label="Tools"
      className="flex shrink-0 gap-1 overflow-x-auto border-b bg-background p-2 md:w-44 md:flex-col md:overflow-y-auto md:border-r md:border-b-0"
    >
      {SHELL_TOOLS.map((tool) => {
        const Icon = ICONS[tool.id]

        return (
          <Button
            key={tool.id}
            type="button"
            variant={tool.id === selected ? "secondary" : "ghost"}
            aria-pressed={tool.id === selected}
            className="h-auto min-w-16 flex-col gap-1 px-1 py-2 text-[0.65rem] md:w-full md:flex-row md:justify-start"
            onClick={() => {
              onSelect(tool.id)
            }}
          >
            <Icon />
            {tool.label}
          </Button>
        )
      })}
      {ANALYSIS_GROUPS.map((category) => (
        <div key={category} className="flex gap-1 md:flex-col">
          <p className="px-1 pt-2 text-[0.62rem] font-medium tracking-[0.14em] text-muted-foreground uppercase">
            {category}
          </p>
          {ANALYSIS_TOOLS.filter((tool) => tool.category === category).map(
            (tool) => (
              <Button
                key={tool.id}
                type="button"
                variant={tool.id === selected ? "secondary" : "ghost"}
                aria-pressed={tool.id === selected}
                className="h-auto min-w-16 justify-start px-2 py-1.5 text-left text-[0.7rem] md:w-full"
                onClick={() => {
                  onSelect(tool.id)
                }}
              >
                {tool.label}
              </Button>
            )
          )}
        </div>
      ))}
    </nav>
  )
}
