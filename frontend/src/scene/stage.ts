import { formatUtc } from "@/lib/format"
import { isAnalysisTool, type ToolId } from "@/scene/tools"
import type { JobResult, SceneResponse } from "@/types"

export type StageSource = "quicklook" | "thumbnail" | "video"

export interface StageSourceChoice {
  id: StageSource
  label: string
  enabled: boolean
}

export interface StageView {
  loading: boolean
  media: "image" | "video"
  src: string | null
  alt: string
  label: string
  emptyMessage: string
  /** Quicklook, thumbnail, and video. Hidden while an analysis picture is up. */
  showSources: boolean
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
  results: JobResult,
  libraryLoading = false
): StageView {
  if (!scene) {
    return {
      loading: false,
      media: "image",
      src: null,
      alt: "SAR quicklook",
      label: "Quicklook",
      emptyMessage:
        libraryLoading || loading
          ? "Opening the library."
          : "Select a downloaded scene from the library.",
      showSources: false,
    }
  }

  const overview = analysisOverview(tool, results.overview_url)

  if (overview) {
    return {
      loading: false,
      media: "image",
      src: overview,
      alt: "Analysis picture with its legend",
      label: "Analysis picture. The legend is part of the image.",
      emptyMessage: "",
      showSources: false,
    }
  }

  if (source === "video" && scene.video_url) {
    return {
      loading: false,
      media: "video",
      src: scene.video_url,
      alt: `Video of ${scene.scene_id}`,
      label: previewCaption("Video", scene),
      emptyMessage: "",
      showSources: true,
    }
  }

  if (source === "thumbnail" && scene.thumbnail_url) {
    return {
      loading,
      media: "image",
      src: scene.thumbnail_url,
      alt: `Thumbnail of ${scene.scene_id}`,
      label: previewCaption("Thumbnail", scene),
      emptyMessage: "The thumbnail is not on disk.",
      showSources: true,
    }
  }

  return {
    loading,
    media: "image",
    src: scene.preview_url,
    alt: `SAR quicklook of ${scene.scene_id}`,
    label: previewCaption("Quicklook", scene),
    emptyMessage:
      "This scene has no quicklook on disk. Download the preview pack from the catalog.",
    showSources: true,
  }
}

function previewCaption(name: string, scene: SceneResponse): string {
  return `${name} · ${formatUtc(scene.collected_at)}`
}

export function analysisRunDisabled(tool: { locked: boolean } | null): boolean {
  return tool == null || tool.locked
}

function analysisOverview(
  tool: ToolId | null,
  url: string | null
): string | null {
  if (!tool || !isAnalysisTool(tool) || !url) {
    return null
  }

  if (!url.includes(`/analysis/${tool}/`)) {
    return null
  }

  return url
}
