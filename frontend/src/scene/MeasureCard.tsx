import { LoaderCircle, Play } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import type { JobSnapshot } from "@/types"

interface MeasureCardProps {
  snapshot: JobSnapshot | null
  isRunning: boolean
  startError: string | null
  onMeasure: () => void
  showHeading?: boolean
  disabled?: boolean
}

export function MeasureCard({
  snapshot,
  isRunning,
  startError,
  onMeasure,
  showHeading = true,
  disabled = false,
}: MeasureCardProps) {
  const stepIndex = snapshot?.step_index ?? 0
  const stepCount = snapshot?.step_count || 9
  const sentence = snapshot?.sentence ?? ""
  const failed = snapshot?.status === "failed"
  const failure = failed ? snapshot?.error || sentence : startError
  const showFailure = Boolean(failure) && failure !== sentence
  const percent = Math.min(100, Math.round((stepIndex / stepCount) * 100))

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        {showHeading ? (
          <div>
            <h2 className="font-heading text-base font-medium">Measurement</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              One background job. It reads the GRD and the dwell stack if they
              are already on disk. It does not download them.
            </p>
          </div>
        ) : null}

        <Button
          type="button"
          size="lg"
          className="w-full"
          disabled={isRunning || disabled}
          onClick={onMeasure}
        >
          {isRunning ? (
            <LoaderCircle className="animate-spin" />
          ) : (
            <Play />
          )}
          {isRunning ? "Measuring" : "Measure scene"}
        </Button>

        <div className="flex flex-col gap-2" role="status" aria-live="polite">
          {isRunning ? (
            <Progress value={percent} className="flex-col gap-2">
              <span className="text-xs text-muted-foreground tabular-nums">
                {stepIndex} of {stepCount}
              </span>
            </Progress>
          ) : (
            <p className="text-xs text-muted-foreground">
              {snapshot?.status === "done" ? "Finished." : "Ready."}
            </p>
          )}

          {sentence ? (
            <p className={failed ? "text-sm text-destructive" : "text-sm"}>
              {sentence}
            </p>
          ) : null}
        </div>

        {showFailure && failure ? (
          <Alert variant="destructive">
            <AlertTitle>Measurement failed</AlertTitle>
            <AlertDescription>{failure}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}
