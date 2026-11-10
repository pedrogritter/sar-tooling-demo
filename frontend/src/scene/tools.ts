export const TOOLS = [
  {
    id: "preview",
    label: "Preview",
    description:
      "The quicklook, in the product's own pixel orientation. Not a map and not a detection layer.",
  },
  {
    id: "measure",
    label: "Measure",
    description:
      "One background job. It reads the GRD and the dwell stack if they are already on disk. It does not download them.",
  },
] as const

export type ToolId = (typeof TOOLS)[number]["id"]

export function toolById(id: ToolId) {
  const tool = TOOLS.find((candidate) => candidate.id === id)

  if (!tool) {
    return TOOLS[0]
  }

  return tool
}
