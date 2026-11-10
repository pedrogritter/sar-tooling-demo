import type { LucideIcon } from "lucide-react"

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "cn"

export interface RailTool {
  id: string
  label: string
  icon: LucideIcon
}

interface EdgeRailProps {
  label: string
  tools: RailTool[]
  selected: string | null
  side: "left" | "right"
  onSelect: (id: string) => void
}

/** Icon rail. The same tool again closes that edge's panel. */
export function EdgeRail({
  label,
  tools,
  selected,
  side,
  onSelect,
}: EdgeRailProps) {
  return (
    <nav
      aria-label={label}
      className="flex w-12 shrink-0 flex-col items-center gap-1 bg-sidebar py-2"
    >
      {tools.map((tool) => {
        const Icon = tool.icon
        const open = selected === tool.id

        return (
          <Tooltip key={tool.id}>
            <TooltipTrigger
              type="button"
              aria-pressed={open}
              aria-label={tool.label}
              className={cn(
                "flex size-8 items-center justify-center rounded-lg text-sidebar-foreground hover:bg-sidebar-accent",
                open && "bg-sidebar-accent text-sidebar-accent-foreground"
              )}
              onClick={() => {
                onSelect(tool.id)
              }}
            >
              <Icon className="size-4" />
            </TooltipTrigger>
            <TooltipContent side={side === "left" ? "right" : "left"}>
              {tool.label}
            </TooltipContent>
          </Tooltip>
        )
      })}
    </nav>
  )
}
