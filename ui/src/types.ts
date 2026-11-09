export type BoundingBox = [
  west: number,
  south: number,
  east: number,
  north: number,
];

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export interface JsonObject {
  [key: string]: JsonValue | undefined;
}

export interface MeasurementBasin extends JsonObject {
  area_km2?: number;
  median_sigma0_db?: number;
}

export interface MeasurementBridge extends JsonObject {
  area_m2?: number;
  length_m?: number;
  width_m?: number;
  peak_sigma0_db?: number;
}

export interface MeasurementReturn extends JsonObject {
  motion?: string;
  displacement_m?: number;
  speed_m_s?: number;
  area_m2?: number;
  peak_sigma0_db?: number;
}

export interface Measurement extends JsonObject {
  water_km2?: number;
  scene_km2?: number;
  basins?: MeasurementBasin[];
  bridge?: MeasurementBridge;
  returns?: MeasurementReturn[];
}

export interface SceneResponse {
  scene_id: string;
  collected_at: string;
  start_at: string;
  end_at: string;
  platform: string;
  mode: string;
  band: string;
  polarizations: string[];
  orbit_state: string;
  incidence_angle: number;
  bbox: BoundingBox;
  preview_url: string | null;
  measurement: Measurement | null;
  briefing_html: string | null;
  overview_url: string | null;
}

export interface MeasureJobAccepted {
  job_id: string;
  status: "running";
}

export interface JobResult {
  measurement: Measurement | null;
  briefing_html: string | null;
  overview_url: string | null;
}

export interface JobSnapshot {
  status: "idle" | "running" | "done" | "failed";
  step_index: number;
  step_count: number;
  sentence: string;
  error: string | null;
  result: JobResult | null;
}

export interface RunPanelProps {
  fetchCurrentJob: () => Promise<JobSnapshot>;
  onJobDone: (result: JobResult) => void;
  startMeasureJob: () => Promise<MeasureJobAccepted>;
}

export interface ResultsPanelProps {
  briefing_html: string | null;
  measurement: Measurement | null;
  overview_url: string | null;
}
