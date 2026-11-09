import type { SceneResponse } from "@/types";
import "@/preview/preview.css";

interface PreviewProps {
  scene: SceneResponse | null;
  loading: boolean;
  error: string | null;
}

const quicklookCaption =
  "Quicklook raster from qlk-cog.tif, downsampled for this page. Pixels stay in the product orientation. This is not a map overlay and not a detection layer.";

export function Preview({ scene, loading, error }: PreviewProps) {
  const facts = scene ? collectFacts(scene) : [];

  return (
    <section className="scene-preview" aria-labelledby="preview-heading">
      <div className="scene-preview__layout">
        <figure className="scene-preview__figure">
          {scene?.preview_url ? (
            <img
              className="scene-preview__image"
              src="/quicklook.png"
              alt={`SAR quicklook of ${scene.scene_id}, covering the 25 de Abril bridge`}
            />
          ) : (
            <p className="scene-preview__missing">
              The quicklook file is not on disk. From the repository root, run python3
              scene.py.
            </p>
          )}
          <figcaption className="scene-preview__caption">{quicklookCaption}</figcaption>
        </figure>

        <section className="scene-preview__meta" aria-labelledby="preview-heading">
          <h2 className="scene-preview__heading" id="preview-heading">
            Collect
          </h2>
          {loading ? (
            <p className="scene-preview__status">Loading scene metadata.</p>
          ) : error ? (
            <p className="scene-preview__status scene-preview__status--error">{error}</p>
          ) : (
            <dl className="scene-preview__facts">
              {facts.map((fact) => (
                <div className="scene-preview__fact" key={fact.label}>
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>
    </section>
  );
}

function collectFacts(scene: SceneResponse) {
  return [
    { label: "Collected", value: formatUtc(scene.collected_at) },
    {
      label: "Window",
      value: `${formatUtc(scene.start_at)} - ${formatUtc(scene.end_at)}`,
    },
    { label: "Platform", value: scene.platform },
    { label: "Mode", value: scene.mode },
    { label: "Band", value: scene.band },
    { label: "Polarization", value: scene.polarizations.join(", ") },
    { label: "Orbit", value: scene.orbit_state },
    { label: "Incidence angle", value: `${scene.incidence_angle.toFixed(1)} deg` },
    { label: "Bounding box", value: formatBbox(scene.bbox) },
  ];
}

function formatUtc(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const formatter = new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short",
  });

  return formatter.format(date).replace(" at ", ", ");
}

function formatBbox([west, south, east, north]: SceneResponse["bbox"]): string {
  return `${formatCoordinate(west)}, ${formatCoordinate(south)}, ${formatCoordinate(
    east,
  )}, ${formatCoordinate(north)} (west, south, east, north)`;
}

function formatCoordinate(value: number): string {
  return value.toFixed(3);
}
