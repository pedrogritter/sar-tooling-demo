import {
  Activity,
  ArrowLeftRight,
  Boxes,
  Building,
  CalendarClock,
  ChartBar,
  ChevronRight,
  CircleDashed,
  CircleDot,
  FileText,
  FolderOpen,
  Image,
  LandPlot,
  Layers,
  Lock,
  Repeat,
  Search,
  Sigma,
  Spline,
  WavesHorizontal,
  Wind,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  ANALYSIS_GROUPS,
  ANALYSIS_TOOLS,
  isGroupOpen,
  SHELL_TOOLS,
  type ToolId,
} from "@/scene/tools"
import type { AnalysisTool } from "@/types"

const ICONS: Record<(typeof SHELL_TOOLS)[number]["id"], LucideIcon> = {
  preview: Image,
  catalog: Search,
  library: FolderOpen,
  report: FileText,
}

const TOOL_ICONS: Record<(typeof ANALYSIS_TOOLS)[number]["id"], LucideIcon> = {
  "open-water": WavesHorizontal,
  "sea-roughness": Wind,
  "built-up": Building,
  "returns-on-water": CircleDot,
  "long-structure": Spline,
  "dwell-motion": Activity,
  "amplitude-change": ArrowLeftRight,
  "water-persistence": Layers,
  "sea-state": ChartBar,
  "dark-sea-anomaly": CircleDashed,
  "shoreline-series": LandPlot,
  "date-of-change": CalendarClock,
  "repeat-returns": Repeat,
  "site-activity": Boxes,
  "stack-mean": Sigma,
}

interface ToolPickerProps {
  selected: ToolId | null
  tools: AnalysisTool[]
  onSelect: (tool: ToolId) => void
}

/** Tool column. Scene tools stay on top. Measurement groups start collapsed. */
export function ToolPicker({ selected, tools, onSelect }: ToolPickerProps) {
  const [opened, setOpened] = useState<string[]>([])

  function toggleGroup(category: string) {
    setOpened((current) =>
      current.includes(category)
        ? current.filter((item) => item !== category)
        : [...current, category]
    )
  }

  return (
    <nav
      aria-label="Tools"
      className="flex shrink-0 gap-1 overflow-x-auto border-b bg-background p-2 md:w-44 md:flex-col md:overflow-y-auto md:border-r md:border-b-0"
    >
      <div className="flex shrink-0 gap-1 md:flex-col">
        <p className="px-1 pt-1 text-xs font-medium text-muted-foreground md:pt-2">
          Scene
        </p>
        {SHELL_TOOLS.map((tool) => {
          const Icon = ICONS[tool.id]

          return (
            <Button
              key={tool.id}
              type="button"
              variant={tool.id === selected ? "secondary" : "ghost"}
              aria-pressed={tool.id === selected}
              className="h-auto min-w-16 flex-col gap-1 px-1 py-2 text-xs md:w-full md:flex-row md:justify-start"
              onClick={() => {
                onSelect(tool.id)
              }}
            >
              <Icon />
              {tool.label}
            </Button>
          )
        })}
      </div>
      {ANALYSIS_GROUPS.map((category) => {
        const open = isGroupOpen(category, selected, opened)

        return (
          <div key={category} className="flex shrink-0 gap-1 md:flex-col">
            <button
              type="button"
              aria-expanded={open}
              className="flex h-auto min-w-16 shrink-0 items-center gap-1 rounded-md px-1 py-1 text-left text-xs font-medium text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 md:w-full"
              onClick={() => {
                toggleGroup(category)
              }}
            >
              <ChevronRight
                className={`size-3 shrink-0 transition-transform duration-150 motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
              />
              {category}
            </button>
            {open
              ? ANALYSIS_TOOLS.filter((tool) => tool.category === category).map(
                  (tool) => {
                    const match = tools.find((item) => item.id === tool.id)
                    const locked = match?.locked === true
                    const Icon = TOOL_ICONS[tool.id]

                    return (
                      <Button
                        key={tool.id}
                        type="button"
                        variant={tool.id === selected ? "secondary" : "ghost"}
                        aria-pressed={tool.id === selected}
                        title={locked ? match?.reason : undefined}
                        className="h-auto min-w-16 justify-start px-2 py-1.5 text-left text-xs md:w-full md:pl-5"
                        onClick={() => {
                          onSelect(tool.id)
                        }}
                      >
                        <Icon className="size-3" />
                        <span className="min-w-0 flex-1 truncate">
                          {tool.label}
                        </span>
                        {locked ? <Lock className="size-3" /> : null}
                      </Button>
                    )
                  }
                )
              : null}
          </div>
        )
      })}
    </nav>
  )
}
