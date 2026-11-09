import type { Measurement, SceneResponse } from "@/types";

import { measurementToReturnRows } from "./rows";
import "./results.css";

type ResultsPanelProps = {
  scene?: SceneResponse | null;
  measurement?: Measurement | null;
  briefingHtml?: string | null;
  briefing_html?: string | null;
  overviewUrl?: string | null;
  overview_url?: string | null;
};

type NumericMeasurement = Measurement & {
  water_km2?: number | null;
  basins?: Array<{
    area_km2?: number | null;
    median_sigma0_db?: number | null;
  }>;
  bridge?: {
    length_m?: number | null;
    width_m?: number | null;
    peak_sigma0_db?: number | null;
  } | null;
};

export function ResultsPanel({
  scene = null,
  measurement: measurementProp,
  briefingHtml,
  briefing_html: briefingHtmlSnake,
  overviewUrl,
  overview_url: overviewUrlSnake,
}: ResultsPanelProps) {
  const measurement = measurementProp ?? scene?.measurement ?? null;
  const briefing = briefingHtml ?? briefingHtmlSnake ?? scene?.briefing_html ?? null;
  const overview = overviewUrl ?? overviewUrlSnake ?? scene?.overview_url ?? null;

  if (measurement === null) {
    return null;
  }

  const values = measurement as NumericMeasurement;
  const rows = measurementToReturnRows(measurement);

  return (
    <section className="results" aria-labelledby="results-heading">
      <div className="results__header">
        <p className="results__kicker">Measurement</p>
        <h2 className="results__heading" id="results-heading">
          Results
        </h2>
      </div>

      <div className="results__layout">
        <div className="results__numbers">
          <dl className="results__summary">
            <div className="results__summary-item">
              <dt>Water area</dt>
              <dd>{formatNumber(values.water_km2, "km2")}</dd>
            </div>
            {values.basins?.slice(0, 2).map((basin, index) => (
              <div className="results__summary-item" key={`basin-${index + 1}`}>
                <dt>Basin {index + 1}</dt>
                <dd>
                  {formatNumber(basin.area_km2, "km2")}
                  <span className="results__muted">
                    {" "}
                    median sigma0 {formatNumber(basin.median_sigma0_db, "dB")}
                  </span>
                </dd>
              </div>
            ))}
            <div className="results__summary-item">
              <dt>Deck length</dt>
              <dd>{formatNumber(values.bridge?.length_m, "m")}</dd>
            </div>
            <div className="results__summary-item">
              <dt>Deck width</dt>
              <dd>
                {formatNumber(values.bridge?.width_m, "m")}
                <span className="results__muted">
                  {" "}
                  bright radar return with layover included, not roadway width
                </span>
              </dd>
            </div>
          </dl>

          <div className="results__table-wrap">
            <table className="results__table">
              <caption>Bright returns</caption>
              <thead>
                <tr>
                  <th scope="col">Row</th>
                  <th scope="col">Motion</th>
                  <th scope="col">Area</th>
                  <th scope="col">Speed</th>
                  <th scope="col">Peak sigma0</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={row.id}>
                    <th scope="row">Bright return {index + 1}</th>
                    <td>{row.motion}</td>
                    <td>{formatNumber(row.areaM2, "m2")}</td>
                    <td>{formatNumber(row.speedMS, "m/s")}</td>
                    <td>{formatNumber(row.peakSigma0Db, "dB")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {overview ? (
          <figure className="results__overview">
            <img src={overview} alt="Measurement overview for the bright returns" />
            <figcaption>Overview image drawn by the measurement job.</figcaption>
          </figure>
        ) : null}
      </div>

      {briefing ? (
        <article
          className="results__briefing"
          dangerouslySetInnerHTML={{ __html: briefing }}
        />
      ) : null}
    </section>
  );
}

function formatNumber(value: number | null | undefined, unit: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "not reported";
  }

  return `${new Intl.NumberFormat("en", {
    maximumFractionDigits: unit === "dB" ? 2 : 1,
  }).format(value)} ${unit}`;
}
