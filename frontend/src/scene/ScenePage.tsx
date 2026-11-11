import { Moon, Radar, Sun } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import {
  clearDemoData,
  fetchDownload,
  fetchLibrary,
  fetchSceneById,
} from "@/api"
import { CatalogPanel } from "@/catalog/CatalogPanel"
import { DownloadDock } from "@/catalog/DownloadDock"
import { LibraryPanel } from "@/catalog/LibraryPanel"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useTheme } from "@/components/theme-provider"
import { AnalysisPane } from "@/scene/AnalysisPane"
import { demoBannerVisible } from "@/scene/placeholder"
import { ImageStage } from "@/scene/ImageStage"
import { MetadataOverlay } from "@/scene/MetadataOverlay"
import { ReportView } from "@/scene/ReportView"
import { ToolPicker } from "@/scene/ToolPicker"
import { stageFor, type StageSource } from "@/scene/stage"
import {
  isAnalysisTool,
  selectTool,
  toolById,
  type ToolId,
} from "@/scene/tools"
import type {
  DownloadSnapshot,
  JobResult,
  LibraryScene,
  SceneResponse,
} from "@/types"

const EMPTY_RESULT: JobResult = {
  measurement: null,
  briefing_html: null,
  overview_url: null,
}

/**
 * Canvas shell. One tool column, the stage, and a single pane for the
 * selected tool. Catalog and library load a scene and return to Preview.
 */
export function ScenePage() {
  const [tool, setTool] = useState<ToolId | null>("preview")
  const [scenes, setScenes] = useState<LibraryScene[]>([])
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(true)
  const [scene, setScene] = useState<SceneResponse | null>(null)
  const [sceneError, setSceneError] = useState<string | null>(null)
  const [sceneLoading, setSceneLoading] = useState(false)
  const [results, setResults] = useState<JobResult>(EMPTY_RESULT)
  const [stageSource, setStageSource] = useState<StageSource>("quicklook")
  const [metadataVisible, setMetadataVisible] = useState(true)
  const [download, setDownload] = useState<DownloadSnapshot | null>(null)
  const [dockExpanded, setDockExpanded] = useState(false)
  const [downloadWatch, setDownloadWatch] = useState(0)
  const [clearingDemo, setClearingDemo] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  const loadLibrary = useCallback(async () => {
    setLibraryLoading(true)

    try {
      const next = await fetchLibrary()
      setScenes(next.scenes)
      setLibraryError(null)
      return next.scenes
    } catch (error) {
      setLibraryError(messageFrom(error))
      return []
    } finally {
      setLibraryLoading(false)
    }
  }, [])

  const openScene = useCallback(async (sceneId: string) => {
    setSceneLoading(true)
    setSceneError(null)

    try {
      const next = await fetchSceneById(sceneId)
      setScene(next)
      setResults(resultFromScene(next))
      setStageSource("quicklook")
    } catch (error) {
      setSceneError(messageFrom(error))
    } finally {
      setSceneLoading(false)
    }
  }, [])

  const openSceneOnStage = useCallback(
    (sceneId: string) => {
      void openScene(sceneId)
      setTool("preview")
    },
    [openScene]
  )

  const clearDemo = useCallback(async () => {
    const sceneId = scene?.scene_id
    setClearingDemo(true)
    setClearError(null)

    try {
      await clearDemoData()
      await loadLibrary()
      if (sceneId) {
        await openScene(sceneId)
      }
    } catch (error) {
      setClearError(messageFrom(error))
    } finally {
      setClearingDemo(false)
    }
  }, [loadLibrary, openScene, scene?.scene_id])

  useEffect(() => {
    let active = true

    void loadLibrary().then((loaded) => {
      if (!active) {
        return
      }

      const initial =
        loaded.find((item) => item.is_test_scene) ?? loaded[0] ?? null

      if (initial) {
        void openScene(initial.scene_id)
      }
    })

    return () => {
      active = false
    }
  }, [loadLibrary, openScene])

  useEffect(() => {
    let active = true

    async function poll() {
      try {
        const next = await fetchDownload()

        if (!active) {
          return
        }

        setDownload(next)

        if (next.status === "running") {
          window.setTimeout(() => {
            if (active) {
              void poll()
            }
          }, 400)
        }

        if (next.status === "done") {
          void loadLibrary()
        }
      } catch (error) {
        if (active) {
          setDownload((current) =>
            current
              ? { ...current, status: "failed", error: messageFrom(error) }
              : current
          )
        }
      }
    }

    void poll()
    return () => {
      active = false
    }
  }, [downloadWatch, loadLibrary])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return
      }

      const target = event.target
      if (
        target instanceof HTMLElement &&
        target.closest("input, textarea, select")
      ) {
        return
      }

      setTool(null)
    }

    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("keydown", onKey)
    }
  }, [])

  const stage = stageFor(tool, stageSource, scene, sceneLoading, results)
  const selected = tool ? toolById(tool) : null

  return (
    <div className="flex h-svh flex-col overflow-hidden bg-background">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b px-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Radar className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-medium tracking-tight">
            {scene?.is_test_scene
              ? "25 de Abril bridge"
              : (scene?.scene_id ?? "ICEYE open data")}
          </h1>
          <p className="truncate font-mono text-[0.65rem] text-muted-foreground">
            {scene?.scene_id ?? "Select a downloaded scene"}
          </p>
        </div>
        <ThemeToggle />
      </header>
      {demoBannerVisible(scene) ? (
        <div className="flex flex-wrap items-center gap-3 border-b bg-muted px-3 py-2">
          <p className="min-w-0 flex-1 text-sm">
            {scene?.placeholder_note ??
              "Demo placeholder. These pictures and numbers were not measured from an ICEYE raster."}
          </p>
          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={clearingDemo}
            onClick={() => {
              void clearDemo()
            }}
          >
            {clearingDemo ? "Clearing demo data" : "Clear demo data"}
          </Button>
          {clearError ? (
            <p className="w-full text-sm text-destructive">{clearError}</p>
          ) : null}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <ToolPicker
          selected={tool}
          onSelect={(next) => {
            setResults(EMPTY_RESULT)
            setTool((current) => selectTool(current, next))
          }}
        />

        {tool === "report" ? (
          <ReportView
            key={scene?.scene_id ?? "no-scene"}
            sceneId={scene?.scene_id ?? null}
            onClose={() => {
              setTool(null)
            }}
          />
        ) : (
          <div className="relative min-h-[40vh] min-w-0 flex-1 md:min-h-0">
            <ImageStage
              loading={stage.loading}
              src={stage.src}
              alt={stage.alt}
              label={stage.label}
              emptyMessage={stage.emptyMessage}
              media={stage.media}
            />
            {metadataVisible ? (
              <MetadataOverlay
                scene={scene}
                loading={sceneLoading}
                error={sceneError}
                onHide={() => {
                  setMetadataVisible(false)
                }}
              />
            ) : (
              <Button
                type="button"
                variant="secondary"
                size="xs"
                className="absolute top-3 right-3 z-10"
                onClick={() => {
                  setMetadataVisible(true)
                }}
              >
                Metadata
              </Button>
            )}
          </div>
        )}

        {tool && tool !== "report" && selected ? (
          <section
            aria-label={selected.label}
            className="flex max-h-[50vh] min-h-0 flex-col border-t md:max-h-none md:w-96 md:border-t-0 md:border-l"
          >
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
              <h2 className="text-sm font-medium">{selected.label}</h2>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={() => {
                  setTool(null)
                }}
              >
                Close
              </Button>
            </div>
            {tool === "preview" ? (
              <PreviewPane
                scene={scene}
                source={stageSource}
                description={selected.description}
                onSource={setStageSource}
              />
            ) : null}
            {tool && isAnalysisTool(tool) ? (
              <ScrollArea className="flex-1">
                <AnalysisPane
                  key={`${tool}:${scene?.placeholder ? "demo" : "scene"}`}
                  sceneId={scene?.scene_id ?? null}
                  toolId={tool}
                  description={selected.description}
                  onResult={(result) => {
                    setResults({
                      ...result,
                      overview_url: result.overview_url
                        ? `${result.overview_url}?drawn=${Date.now()}`
                        : null,
                    })
                  }}
                />
              </ScrollArea>
            ) : null}
            {tool === "catalog" ? (
              <CatalogPanel
                onOpenScene={openSceneOnStage}
                onDownloadStarted={() => {
                  setDockExpanded(true)
                  setDownloadWatch((value) => value + 1)
                }}
              />
            ) : null}
            {tool === "library" ? (
              <LibraryPanel
                scenes={scenes}
                loading={libraryLoading}
                error={libraryError}
                selectedId={scene?.scene_id ?? null}
                onSelect={openSceneOnStage}
                onRefresh={() => {
                  void loadLibrary()
                }}
              />
            ) : null}
          </section>
        ) : null}
      </div>

      <DownloadDock
        snapshot={download}
        expanded={dockExpanded}
        onToggle={() => {
          setDockExpanded((value) => !value)
        }}
        onDismiss={() => {
          setDownload(null)
          setDockExpanded(false)
        }}
      />
    </div>
  )
}

function PreviewPane({
  scene,
  source,
  description,
  onSource,
}: {
  scene: SceneResponse | null
  source: StageSource
  description: string
  onSource: (source: StageSource) => void
}) {
  const choices: { id: StageSource; label: string; enabled: boolean }[] = [
    {
      id: "quicklook",
      label: "Quicklook",
      enabled: Boolean(scene?.preview_url),
    },
    {
      id: "thumbnail",
      label: "Thumbnail",
      enabled: Boolean(scene?.thumbnail_url),
    },
    { id: "video", label: "Dwell video", enabled: Boolean(scene?.video_url) },
  ]

  return (
    <div className="flex flex-col gap-3 p-3">
      <p className="text-sm text-muted-foreground">{description}</p>
      {choices.map((choice) => (
        <Button
          key={choice.id}
          type="button"
          variant={source === choice.id ? "secondary" : "outline"}
          disabled={!choice.enabled}
          onClick={() => {
            onSource(choice.id)
          }}
        >
          {choice.label}
        </Button>
      ))}
    </div>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const dark = isDarkTheme(theme)

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => {
        setTheme(dark ? "light" : "dark")
      }}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}

function isDarkTheme(theme: string): boolean {
  if (theme === "dark") {
    return true
  }

  if (theme === "light") {
    return false
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

function resultFromScene(scene: SceneResponse): JobResult {
  return {
    measurement: scene.measurement,
    briefing_html: scene.briefing_html,
    overview_url: scene.overview_url,
  }
}

function messageFrom(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message
  }

  return "The request failed."
}
