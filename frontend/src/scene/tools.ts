export const SHELL_TOOLS = [
  {
    id: "preview",
    label: "Preview",
    description:
      "The quicklook, in the product's own pixel orientation. Not a map and not a detection layer.",
  },
  {
    id: "catalog",
    label: "Catalog",
    description: "Search ICEYE open data and download a scene into this machine.",
  },
  {
    id: "library",
    label: "Library",
    description: "Scenes already on disk, ready to open on the stage.",
  },
] as const

export const ANALYSIS_TOOLS = [
  {
    id: "open-water",
    label: "Open water",
    category: "Surface",
    description: "Dark smooth water. Area, fraction, and median sigma-nought.",
  },
  {
    id: "sea-roughness",
    label: "Sea roughness",
    category: "Surface",
    description: "Calm water against wind-roughened water, inside the water mask.",
  },
  {
    id: "built-up",
    label: "Built-up return",
    category: "Surface",
    description: "Bright clusters on land. Fraction of land and a cluster count.",
  },
  {
    id: "returns-on-water",
    label: "Returns on water",
    category: "Objects",
    description:
      "Compact bright returns that touch the water. The label stays bright return.",
  },
  {
    id: "long-structure",
    label: "Long structure",
    category: "Objects",
    description: "A long bright return along the waterline.",
  },
  {
    id: "dwell-motion",
    label: "Dwell motion",
    category: "Motion",
    description: "Tracks of bright returns during the dwell.",
  },
  {
    id: "amplitude-change",
    label: "Amplitude change",
    category: "Change",
    description: "Earlier date in red, later date in cyan. Needs the same look.",
  },
  {
    id: "water-persistence",
    label: "Water persistence",
    category: "Stack",
    description: "How many dates each pixel is water.",
  },
  {
    id: "sea-state",
    label: "Sea state",
    category: "Stack",
    description: "Median sigma-nought of the water on each date.",
  },
  {
    id: "dark-sea-anomaly",
    label: "Dark sea anomaly",
    category: "Stack",
    description:
      "A patch darker than the stack median of the sea. Extent only, not a spill.",
  },
  {
    id: "shoreline-series",
    label: "Shoreline",
    category: "Stack",
    description: "The waterline once per date.",
  },
  {
    id: "date-of-change",
    label: "Date of change",
    category: "Stack",
    description:
      "The date a pixel left the stack median, when the departure is at least 3 dB and the patch is at least 8 pixels.",
  },
  {
    id: "repeat-returns",
    label: "Repeat returns",
    category: "Stack",
    description: "A bright return seen on many dates against one seen once.",
  },
  {
    id: "site-activity",
    label: "Site activity",
    category: "Stack",
    description: "A bright cluster that appears or leaves.",
  },
  {
    id: "stack-mean",
    label: "Stack mean",
    category: "Stack",
    description: "The mean of the matched dates.",
  },
] as const

export const TOOLS = [...SHELL_TOOLS, ...ANALYSIS_TOOLS] as const

export type ToolId = (typeof TOOLS)[number]["id"]

export const ANALYSIS_GROUPS = [
  "Surface",
  "Objects",
  "Motion",
  "Change",
  "Stack",
] as const

/** Choosing the open tool closes the pane. Any other choice replaces it. */
export function selectTool(
  current: ToolId | null,
  next: ToolId
): ToolId | null {
  return current === next ? null : next
}

export function toolById(id: string) {
  const tool = TOOLS.find((candidate) => candidate.id === id)

  if (!tool) {
    return TOOLS[0]
  }

  return tool
}

export function isAnalysisTool(id: ToolId): boolean {
  return ANALYSIS_TOOLS.some((tool) => tool.id === id)
}
