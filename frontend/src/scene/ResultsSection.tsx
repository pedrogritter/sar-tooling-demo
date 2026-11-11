import { Card, CardContent } from "@/components/ui/card"
import { formatMeasure, formatPercent, measurementNumber } from "@/lib/format"
import { measurementToReturnRows } from "@/scene/rows"
import type { JobResult, Measurement } from "@/types"

import { ReturnsTable } from "@/scene/ReturnsTable"

interface ResultsSectionProps {
  result: JobResult
}

export function ResultsSection({ result }: ResultsSectionProps) {
  const measurement = result.measurement

  return (
    <section
      className="flex scroll-mt-24 flex-col gap-4"
      aria-labelledby="results-heading"
    >
      <div>
        <h2 id="results-heading" className="text-lg font-medium tracking-tight">
          Results
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          A square on the overview is a bright radar return.
        </p>
      </div>

      {measurement ? (
        <MeasurementView
          measurement={measurement}
          briefingHtml={result.briefing_html}
          overviewUrl={result.overview_url}
        />
      ) : (
        <Card size="sm">
          <CardContent className="text-sm text-muted-foreground">
            No measurement on disk yet. Measure scene uses files already on
            this machine.
          </CardContent>
        </Card>
      )}
    </section>
  )
}

function MeasurementView({
  measurement,
  briefingHtml,
  overviewUrl,
}: {
  measurement: Measurement
  briefingHtml: string | null
  overviewUrl: string | null
}) {
  const rows = measurementToReturnRows(measurement)
  const basins = measurement.basins ?? []
  const sceneArea = measurementNumber(measurement, "scene_km2")
  const waterFraction = measurementNumber(measurement, "water_fraction")

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <Stat
          label="Water area"
          value={formatMeasure(measurement.water_km2, "km2")}
          detail={waterDetail(sceneArea, waterFraction)}
        />
        <Stat
          label="Water component 1"
          value={formatMeasure(basins[0]?.area_km2, "km2")}
          detail={basinDetail(basins[0]?.median_sigma0_db)}
        />
        <Stat
          label="Water component 2"
          value={formatMeasure(basins[1]?.area_km2, "km2")}
          detail={basinDetail(basins[1]?.median_sigma0_db)}
        />
        <Stat
          label="Long return"
          value={formatMeasure(measurement.bridge?.length_m, "m")}
          detail={`Width ${formatMeasure(measurement.bridge?.width_m, "m")}, bright return with layover, not roadway width.`}
        />
      </div>

      <Card>
        <CardContent>
          <ReturnsTable rows={rows} />
        </CardContent>
      </Card>

      <p className="text-xs leading-5 text-muted-foreground">
        {overviewUrl
          ? "The processed image is in the main view."
          : "The overview image is not on disk yet. The main view stays on the quicklook."}
      </p>

      {briefingHtml ? (
        <Card>
          <CardContent className="flex flex-col gap-3">
            <div>
              <h3 className="font-heading text-base font-medium">Briefing</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Prose phrased from the measurement file only.
              </p>
            </div>
            <article
              className="briefing"
              dangerouslySetInnerHTML={{ __html: briefingHtml }}
            />
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function Stat({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail: string
}) {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-1">
        <p className="text-muted-foreground">{label}</p>
        <p className="text-lg font-medium tracking-tight tabular-nums">
          {value}
        </p>
        <p className="text-xs leading-5 text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  )
}

function waterDetail(
  sceneArea: number | null,
  waterFraction: number | null
): string {
  if (sceneArea === null && waterFraction === null) {
    return "Water mask inside this frame."
  }

  return `Scene ${formatMeasure(sceneArea, "km2")} · water ${formatPercent(waterFraction)}.`
}

function basinDetail(median: number | null | undefined): string {
  return `Median sigma0 ${formatMeasure(median, "dB")}.`
}
