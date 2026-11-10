import { ImageOff } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

interface ImageStageProps {
  loading: boolean
  src: string | null
  alt: string
  label: string
  emptyMessage: string
  media?: "image" | "video"
}

/** The center canvas. The selected tool decides which image fills it. */
export function ImageStage({
  loading,
  src,
  alt,
  label,
  emptyMessage,
  media = "image",
}: ImageStageProps) {
  return (
    <figure className="flex h-full min-h-0 flex-col bg-neutral-950">
      <div className="relative min-h-0 flex-1">
        {loading ? (
          <Skeleton className="absolute inset-0 rounded-none bg-neutral-800" />
        ) : null}

        {!loading && src && media === "video" ? (
          <video
            className="absolute inset-0 size-full object-contain"
            src={src}
            controls
            aria-label={alt}
          />
        ) : null}

        {!loading && src && media === "image" ? (
          <img
            className="absolute inset-0 size-full object-contain"
            src={src}
            alt={alt}
            fetchPriority="high"
            decoding="async"
          />
        ) : null}

        {!loading && !src ? (
          <div className="absolute inset-0 flex items-center gap-3 px-6 text-sm text-neutral-300">
            <ImageOff className="size-5 shrink-0" />
            <p className="max-w-md leading-6">{emptyMessage}</p>
          </div>
        ) : null}
      </div>
      <figcaption className="shrink-0 border-t border-white/10 px-3 py-2 text-xs text-neutral-300">
        {label}
      </figcaption>
    </figure>
  )
}
