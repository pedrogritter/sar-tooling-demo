import { useEffect, useState } from "react"

import { fetchGuide } from "@/api"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  GUIDE_CONTENTS_LABEL,
  GUIDE_HEADING,
  GUIDE_LOADING,
  GUIDE_UNAVAILABLE,
  type GuideDocument,
  contentsEntries,
  guideDocument,
} from "@/guide/guide"

interface DocumentationViewProps {
  onClose: () => void
}

/**
 * Usage guide. The stage is replaced while this is open.
 * Sentences come from GET /api/guide. This view does not run a tool.
 */
export function DocumentationView({ onClose }: DocumentationViewProps) {
  const [guide, setGuide] = useState<GuideDocument | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true

    void fetchGuide()
      .then((payload) => {
        if (!active) {
          return
        }

        setGuide(guideDocument(payload))
        setError(null)
      })
      .catch(() => {
        if (active) {
          setGuide(null)
          setError(GUIDE_UNAVAILABLE)
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-sm font-medium">{GUIDE_HEADING}</h2>
        <Button type="button" variant="ghost" size="xs" onClick={onClose}>
          Close
        </Button>
      </div>
      <ScrollArea className="flex-1">
        {loading ? (
          <p className="p-4 text-sm text-muted-foreground">{GUIDE_LOADING}</p>
        ) : null}
        {error ? (
          <p role="alert" className="p-4 text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {guide ? (
          <div className="flex flex-col gap-6 p-4 md:flex-row">
            <nav
              aria-label={GUIDE_CONTENTS_LABEL}
              className="flex shrink-0 flex-col gap-1 md:w-56"
            >
              {contentsEntries(guide).map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className="rounded-md px-2 py-1 text-left text-sm text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                  onClick={() => {
                    window.document
                      .getElementById(entry.id)
                      ?.scrollIntoView({ block: "start" })
                  }}
                >
                  {entry.title}
                </button>
              ))}
            </nav>
            <div className="flex min-w-0 flex-1 flex-col gap-6">
              {guide.sections.map((section) => (
                <section
                  key={section.id}
                  id={section.id}
                  className="flex scroll-mt-4 flex-col gap-2"
                >
                  <h3 className="text-sm font-medium">{section.title}</h3>
                  {section.paragraphs.map((paragraph, index) => (
                    <p
                      key={`${section.id}-${index}`}
                      className="text-sm leading-6 text-muted-foreground"
                    >
                      {paragraph}
                    </p>
                  ))}
                </section>
              ))}
            </div>
          </div>
        ) : null}
      </ScrollArea>
    </div>
  )
}