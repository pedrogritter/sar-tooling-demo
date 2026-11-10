import {
  FolderOpen,
  Image,
  Info,
  Moon,
  Radar,
  Ruler,
  Search,
  Sun,
  Table2,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { fetchDownload, fetchLibrary, fetchSceneById } from "@/api"
import { CatalogPanel } from "@/catalog/CatalogPanel"
import { DownloadDock } from "@/catalog/DownloadDock"
import { LibraryPanel } from "@/catalog/LibraryPanel"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useTheme } from "@/components/theme-provider"
import { collectFacts } from "@/lib/format"
import { FactList } from "@/scene/FactList"
import { ImageStage } from "@/scene/ImageStage"
import { MeasureCard } from "@/scene/MeasureCard"
import { ResultsSection } from "@/scene/ResultsSection"
import { useMeasureJob } from "@/scene/use-measure-job"
import type { DownloadSnapshot, JobResult, LibraryScene, SceneResponse } from "@/types"
import { EdgeRail, type RailTool } from "@/workspace/EdgeRail"
import {
  closeLast,
  CLOSED_EDGES,
  toggleLeft,
  toggleRight,
  type EdgeState,
  type LeftTool,
  type RightTool,
} from "@/workspace/edges"

const LEFT_TOOLS: RailTool[] = [
  { id: "catalog", label: "Catalog", icon: Search },
  { id: "library", label: "Library", icon: FolderOpen },
  { id: "facts", label: "Scene facts", icon: Info },
]

const RIGHT_TOOLS: RailTool[] = [
  { id: "stage", label: "Stage", icon: Image },
  { id: "measure", label: "Measure", icon: Ruler },
  { id: "results", label: "Results", icon: Table2 },
]

const EMPTY_RESULT: JobResult = {
  measurement: null,
  briefing_html: null,
  overview_url: null,
}

type StageSource = "quicklook" | "thumbnail" | "video"

const QUICKLOOK_LABEL =
  "Quicklook. Product orientation, not a map and not a detection layer."

/**
 * One page. Tools sit on the edges and the selected scene fills the center.
 */
export function Workspace() {
  const [edges, setEdges] = useState<EdgeState>(CLOSED_EDGES)
  const [scenes, setScenes] = useState<LibraryScene[]>([])
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(true)
  const [scene, setScene] = useState<SceneResponse | null>(null)
  const [sceneError, setSceneError] = useState<string | null>(null)
  const [sceneLoading, setSceneLoading] = useState(false)
  const [results, setResults] = useState<JobResult>(EMPTY_RESULT)
  const [stageSource, setStageSource] = useState<StageSource>("quicklook")
  const [download, setDownload] = useState<DownloadSnapshot | null>(null)
  const [dockExpanded, setDockExpanded] = useState(false)
  const [downloadWatch, setDownloadWatch] = useState(0)

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
      if (event.key === "Escape") {
        setEdges((current) => closeLast(current))
      }
    }

    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("keydown", onKey)
    }
  }, [])

  const handleJobDone = useCallback((result: JobResult) => {
    setResults(result)
    setEdges((current) => toggleRight({ ...current, right: null }, "results"))
  }, [])

  const job = useMeasureJob(handleJobDone)
  const stage = stageFor(edges, stageSource, scene, sceneLoading, results)
  const left = edges.left
  const right = edges.right

  function selectLeft(id: string) {
    setEdges((current) => toggleLeft(current, id as LeftTool))
  }

  function selectRight(id: string) {
    setEdges((current) => toggleRight(current, id as RightTool))
  }

  return (
    <TooltipProvider>
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

        <div className="flex border-b md:hidden">
          <EdgeRail
            label="Tools"
            tools={[...LEFT_TOOLS, ...RIGHT_TOOLS]}
            selected={left ?? right}
            side="left"
            onSelect={(id) => {
              if (LEFT_TOOLS.some((tool) => tool.id === id)) {
                selectLeft(id)
                return
              }

              selectRight(id)
            }}
          />
        </div>

          <div className="relative flex min-h-0 flex-1">
            <div className="hidden md:flex">
              <EdgeRail
                label="Library tools"
                tools={LEFT_TOOLS}
                selected={left}
                side="left"
                onSelect={selectLeft}
              />
            </div>
            {left ? (
              <div
                className={
                  edges.last === "left"
                    ? "absolute inset-0 z-20 flex min-h-0 flex-col bg-background md:static md:z-auto md:w-96 md:border-r"
                    : "hidden min-h-0 md:flex md:w-96 md:flex-col md:border-r"
                }
              >
                <EdgePanel
                  tool={left}
                  scenes={scenes}
                  libraryError={libraryError}
                  libraryLoading={libraryLoading}
                  scene={scene}
                  sceneError={sceneError}
                  stageSource={stageSource}
                  job={job}
                  results={results}
                  onOpenScene={(sceneId) => {
                    void openScene(sceneId)
                  }}
                  onRefreshLibrary={() => {
                    void loadLibrary()
                  }}
                  onDownloadStarted={() => {
                    setDockExpanded(true)
                    setDownloadWatch((value) => value + 1)
                  }}
                  onStageSource={setStageSource}
                  onClose={() => {
                    setEdges((current) => ({ ...current, left: null }))
                  }}
                />
              </div>
            ) : null}

            <div className="relative min-h-0 min-w-0 flex-1">
              <ImageStage
                loading={stage.loading}
                src={stage.src}
                alt={stage.alt}
                label={stage.label}
                emptyMessage={stage.emptyMessage}
                media={stage.media}
              />
            </div>

            {right ? (
              <div
                className={
                  edges.last === "right"
                    ? "absolute inset-0 z-20 flex min-h-0 flex-col bg-background md:static md:z-auto md:w-96 md:border-l"
                    : "hidden min-h-0 md:flex md:w-96 md:flex-col md:border-l"
                }
              >
                <EdgePanel
                  tool={right}
                  scenes={scenes}
                  libraryError={libraryError}
                  libraryLoading={libraryLoading}
                  scene={scene}
                  sceneError={sceneError}
                  stageSource={stageSource}
                  job={job}
                  results={results}
                  onOpenScene={(sceneId) => {
                    void openScene(sceneId)
                  }}
                  onRefreshLibrary={() => {
                    void loadLibrary()
                  }}
                  onDownloadStarted={() => {
                    setDockExpanded(true)
                    setDownloadWatch((value) => value + 1)
                  }}
                  onStageSource={setStageSource}
                  onClose={() => {
                    setEdges((current) => ({ ...current, right: null }))
                  }}
                />
              </div>
            ) : null}
            <div className="hidden md:flex">
              <EdgeRail
                label="Scene tools"
                tools={RIGHT_TOOLS}
                selected={right}
                side="right"
                onSelect={selectRight}
              />
            </div>
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
    </TooltipProvider>
  )
}

function EdgePanel({
  tool,
  scenes,
  libraryError,
  libraryLoading,
  scene,
  sceneError,
  stageSource,
  job,
  results,
  onOpenScene,
  onRefreshLibrary,
  onDownloadStarted,
  onStageSource,
  onClose,
}: {
  tool: LeftTool | RightTool
  scenes: LibraryScene[]
  libraryError: string | null
  libraryLoading: boolean
  scene: SceneResponse | null
  sceneError: string | null
  stageSource: StageSource
  job: ReturnType<typeof useMeasureJob>
  results: JobResult
  onOpenScene: (sceneId: string) => void
  onRefreshLibrary: () => void
  onDownloadStarted: () => void
  onStageSource: (source: StageSource) => void
  onClose: () => void
}) {
  const open = tool

  return (
    <section aria-label="Tool" className="flex min-h-0 flex-1 flex-col">
      <div className="flex justify-end border-b px-2 py-1">
        <Button type="button" variant="ghost" size="xs" onClick={onClose}>
          Close
        </Button>
      </div>
      {open === "catalog" ? (
        <CatalogPanel
          onOpenScene={onOpenScene}
          onDownloadStarted={onDownloadStarted}
        />
      ) : null}
      {open === "library" ? (
        <LibraryPanel
          scenes={scenes}
          loading={libraryLoading}
          error={libraryError}
          selectedId={scene?.scene_id ?? null}
          onSelect={onOpenScene}
          onRefresh={onRefreshLibrary}
        />
      ) : null}
      {open === "facts" ? (
        <ScrollArea className="flex-1 p-3">
          <h2 className="text-sm font-medium">Scene facts</h2>
          {sceneError ? (
            <p className="mt-2 text-sm text-destructive">{sceneError}</p>
          ) : null}
          {scene ? (
            <div className="mt-3">
              <FactList facts={collectFacts(scene)} dense />
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              Select a downloaded scene to read its collect.
            </p>
          )}
        </ScrollArea>
      ) : null}
      {open === "stage" ? (
        <StagePanel
          scene={scene}
          source={stageSource}
          onSource={onStageSource}
        />
      ) : null}
      {open === "measure" ? (
        <ScrollArea className="flex flex-1 flex-col gap-3 p-3">
          <h2 className="text-sm font-medium">Measure</h2>
          <p className="text-sm text-muted-foreground">
            This measurement describes the 25 de Abril test scene. It reads
            the GRD and the dwell stack already on disk. It does not download
            them, and it does not run on another collect.
          </p>
          <MeasureCard
            snapshot={job.snapshot}
            isRunning={job.isRunning}
            startError={job.startError}
            showHeading={false}
            disabled={!scene?.is_test_scene}
            onMeasure={() => {
              if (scene?.is_test_scene) {
                void job.start()
              }
            }}
          />
        </ScrollArea>
      ) : null}
      {open === "results" ? (
        <ScrollArea className="flex-1 p-3">
          {scene?.is_test_scene ? (
            <ResultsSection result={results} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Results of the bridge measurement are available on the Lisbon
              test scene.
            </p>
          )}
        </ScrollArea>
      ) : null}
    </section>
  )
}

function StagePanel({
  scene,
  source,
  onSource,
}: {
  scene: SceneResponse | null
  source: StageSource
  onSource: (source: StageSource) => void
}) {
  const choices: { id: StageSource; label: string; enabled: boolean }[] = [
    { id: "quicklook", label: "Quicklook", enabled: Boolean(scene?.preview_url) },
    {
      id: "thumbnail",
      label: "Thumbnail",
      enabled: Boolean(scene?.thumbnail_url),
    },
    { id: "video", label: "Dwell video", enabled: Boolean(scene?.video_url) },
  ]

  return (
    <div className="flex flex-col gap-2 p-3">
      <h2 className="text-sm font-medium">Stage</h2>
      <p className="text-sm text-muted-foreground">
        The center shows one product at a time, in the file's own orientation.
      </p>
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

function stageFor(
  edges: EdgeState,
  source: StageSource,
  scene: SceneResponse | null,
  loading: boolean,
  results: JobResult
) {
  const overview =
    edges.right === "results" && scene?.is_test_scene ? results.overview_url : null

  if (overview) {
    return {
      loading: false,
      media: "image" as const,
      src: overview,
      alt: "Measurement overview with water tint and the deck line",
      label: "Measurement overview. Water tint and the deck line.",
      emptyMessage: "",
    }
  }

  if (source === "video" && scene?.video_url) {
    return {
      loading: false,
      media: "video" as const,
      src: scene.video_url,
      alt: `Dwell video of ${scene.scene_id}`,
      label: "Dwell video from the scene folder.",
      emptyMessage: "",
    }
  }

  if (source === "thumbnail" && scene?.thumbnail_url) {
    return {
      loading,
      media: "image" as const,
      src: scene.thumbnail_url,
      alt: scene ? `Thumbnail of ${scene.scene_id}` : "Thumbnail",
      label: "Thumbnail.",
      emptyMessage: "The thumbnail is not on disk.",
    }
  }

  return {
    loading,
    media: "image" as const,
    src: scene?.preview_url ?? null,
    alt: scene ? `SAR quicklook of ${scene.scene_id}` : "SAR quicklook",
    label: QUICKLOOK_LABEL,
    emptyMessage: scene
      ? "This scene has no quicklook on disk. Download the preview pack from the catalog."
      : "Select a downloaded scene from the library.",
  }
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
