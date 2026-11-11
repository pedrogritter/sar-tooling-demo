import { isAnalysisTool, type ToolId } from "@/scene/tools"
import type { JobResult, SceneResponse } from "@/types"

export type StageSource = "quicklook" | "thumbnail" | "video"

const QUICKLOOK_LABEL =
  "Quicklook. Product orientation, not a map and not a detection layer."

export interface StageView {
  loading: boolean
  media: "image" | "video"
  src: string | null
  alt: string
  label: string
  emptyMessage: string
}

/**
 * The analysis picture replaces the quicklook only when this tool wrote it.
 * The Lisbon measurement's `/overview.png` is not that picture.
 */
export function stageFor(
  tool: ToolId | null,
  source: StageSource,
  scene: SceneResponse | null,
  loading: boolean,
  results: JobResult
): StageView {
  const overview = analysisOverview(tool, results.overview_url)

  if (overview) {
    return {
      loading: false,
      media: "image",
      src: overview,
      alt: "Analysis picture with its legend",
      label: "Analysis picture. The legend is part of the image.",
      emptyMessage: "",
    }
  }

  if (source === "video" && scene?.video_url) {
    return {
      loading: false,
      media: "video",
      src: scene.video_url,
      alt: `Dwell video of ${scene.scene_id}`,
      label: "Dwell video from the scene folder.",
      emptyMessage: "",
    }
  }

  if (source === "thumbnail" && scene?.thumbnail_url) {
    return {
      loading,
      media: "image",
      src: scene.thumbnail_url,
      alt: scene ? `Thumbnail of ${scene.scene_id}` : "Thumbnail",
      label: "Thumbnail.",
      emptyMessage: "The thumbnail is not on disk.",
    }
  }

  return {
    loading,
    media: "image",
    src: scene?.preview_url ?? null,
    alt: scene ? `SAR quicklook of ${scene.scene_id}` : "SAR quicklook",
    label: QUICKLOOK_LABEL,
    emptyMessage: scene
      ? "This scene has no quicklook on disk. Download the preview pack from the catalog."
      : "Select a downloaded scene from the library.",
  }
}

export function analysisRunDisabled(
  tool: { locked: boolean } | null
): boolean {
  return tool == null || tool.locked
}

function analysisOverview(tool: ToolId | null, url: string | null): string | null {
  if (!tool || !isAnalysisTool(tool) || !url) {
    return null
  }

  if (!url.includes(`/analysis/${tool}/`)) {
    return null
  }

  return url
}
