import { Settings } from "lucide-react"
import { useEffect, useState } from "react"

import { ApiError, fetchModelKey, saveModelKey } from "@/api"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogPopup,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  settingsBody,
  settingsMessage,
  settingsShowsKeyField,
} from "@/scene/settings"
import type { ModelKeySource } from "@/types"

/**
 * Header control for the process-local OpenAI key. The value is posted to
 * `/api/report/key` and is not kept in this component after the dialog closes.
 */
export function SettingsDialog() {
  const [open, setOpen] = useState(false)
  const [source, setSource] = useState<ModelKeySource | "loading">("loading")
  const [replacing, setReplacing] = useState(false)
  const [draft, setDraft] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setDraft("")
      setReplacing(false)
      setError(null)
      return undefined
    }

    let active = true
    setSource("loading")

    void fetchModelKey()
      .then((status) => {
        if (active) {
          setSource(status.source)
          setError(null)
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setSource("unset")
          setError(messageFrom(caught, "Could not check the OpenAI key."))
        }
      })

    return () => {
      active = false
    }
  }, [open])

  const body = settingsBody(source, replacing)
  const showField = settingsShowsKeyField(body)

  async function saveKey() {
    const apiKey = draft.trim()

    if (!apiKey || saving) {
      return
    }

    setSaving(true)
    setError(null)

    try {
      const status = await saveModelKey(apiKey)
      setSource(status.source)
      setDraft("")
      setReplacing(false)
    } catch (caught) {
      setError(messageFrom(caught, "Could not save the OpenAI key."))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
      }}
    >
      <DialogTrigger
        className={buttonVariants({ variant: "outline", size: "icon" })}
        aria-label="Settings"
      >
        <Settings />
      </DialogTrigger>
      <DialogPopup>
        <div className="flex flex-col gap-3">
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>{settingsMessage(body)}</DialogDescription>
          {showField ? (
            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                void saveKey()
              }}
            >
              <label className="flex flex-col gap-1 text-sm font-medium">
                OpenAI API key
                <Input
                  type="password"
                  name="openai-api-key"
                  autoComplete="off"
                  value={draft}
                  disabled={saving}
                  onValueChange={(value) => {
                    setDraft(value)
                  }}
                />
              </label>
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={saving || !draft.trim()}>
                  {saving ? "Saving key" : "Save key"}
                </Button>
                {body.kind === "form" && body.replacing ? (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setReplacing(false)
                      setDraft("")
                      setError(null)
                    }}
                  >
                    Cancel
                  </Button>
                ) : null}
              </div>
            </form>
          ) : null}
          {body.kind === "session" ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setReplacing(true)
              }}
            >
              Use a different key
            </Button>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <DialogClose
            className={buttonVariants({ variant: "ghost" })}
            disabled={saving}
          >
            Close
          </DialogClose>
        </div>
      </DialogPopup>
    </Dialog>
  )
}

function messageFrom(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message || fallback
  }

  return fallback
}
