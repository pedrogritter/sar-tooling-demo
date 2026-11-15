import { useState } from "react"

import { sendGuideChat } from "@/api"
import { Button } from "@/components/ui/button"
import {
  ASK_LABEL,
  CHAT_LABEL,
  CHAT_PLACEHOLDER,
  CHAT_UNAVAILABLE,
  CLOSE_LABEL,
  SEND_LABEL,
  type GuideChatTurn,
  guideChatTurn,
  openSectionLabel,
  sectionToOpen,
} from "@/guide/chat"

interface GuideChatProps {
  onOpenSection: (sectionId: string) => void
}

interface ChatLine {
  text: string
  turn: GuideChatTurn | null
}

/**
 * Bottom-right chat. It asks the guide route and can open a section.
 * It does not run a tool and it does not download a scene.
 */
export function GuideChat({ onOpenSection }: GuideChatProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState("")
  const [pendingSectionId, setPendingSectionId] = useState<string | null>(null)
  const [lines, setLines] = useState<ChatLine[]>([])
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  async function submit() {
    const message = draft.trim()

    if (!message || sending) {
      return
    }

    setSending(true)
    setError(null)
    setDraft("")
    setLines((current) => [...current, { text: message, turn: null }])

    try {
      const turn = guideChatTurn(await sendGuideChat(message, pendingSectionId))
      const opening = sectionToOpen(turn)

      setLines((current) => [...current, { text: turn.reply, turn }])
      setPendingSectionId(turn.openSection ? null : turn.sectionId)
      if (opening) {
        onOpenSection(opening)
      }
    } catch {
      setError(CHAT_UNAVAILABLE)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed right-4 bottom-20 z-40 flex flex-col items-end gap-2">
      {open ? (
        <section
          aria-label={CHAT_LABEL}
          className="flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-lg border bg-background p-3 shadow-md"
        >
          <h2 className="text-sm font-medium">{CHAT_LABEL}</h2>
          <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
            {lines.map((line, index) => {
              const label = line.turn ? openSectionLabel(line.turn) : null

              return (
                <div key={`${index}-${line.text}`} className="flex flex-col gap-1">
                  <p className="text-sm leading-6">{line.text}</p>
                  {label && line.turn?.sectionId ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      onClick={() => {
                        const sectionId = line.turn?.sectionId

                        if (sectionId) {
                          onOpenSection(sectionId)
                        }
                      }}
                    >
                      {label}
                    </Button>
                  ) : null}
                </div>
              )
            })}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            <input
              value={draft}
              aria-label={CHAT_PLACEHOLDER}
              placeholder={CHAT_PLACEHOLDER}
              className="min-w-0 flex-1 rounded-md border bg-transparent px-2 py-1 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              onChange={(event) => {
                setDraft(event.target.value)
              }}
            />
            <Button type="submit" size="xs" disabled={sending || draft.trim() === ""}>
              {SEND_LABEL}
            </Button>
          </form>
        </section>
      ) : null}
      <Button
        type="button"
        size="sm"
        onClick={() => {
          setOpen((current) => !current)
        }}
      >
        {open ? CLOSE_LABEL : ASK_LABEL}
      </Button>
    </div>
  )
}