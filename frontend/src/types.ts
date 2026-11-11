export type BoundingBox = [
  west: number,
  south: number,
  east: number,
  north: number,
]

export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]

export interface JsonObject {
  [key: string]: JsonValue | undefined
}

export interface MeasurementBasin extends JsonObject {
  area_km2?: number
  median_sigma0_db?: number
}

export interface MeasurementBridge extends JsonObject {
  area_m2?: number
  length_m?: number
  width_m?: number
  peak_sigma0_db?: number
}

export interface MeasurementReturn extends JsonObject {
  motion?: string
  displacement_m?: number
  speed_m_s?: number
  area_m2?: number
  peak_sigma0_db?: number
}

export interface Measurement extends JsonObject {
  water_km2?: number
  scene_km2?: number
  water_fraction?: number
  basins?: MeasurementBasin[]
  bridge?: MeasurementBridge
  returns?: MeasurementReturn[]
  summary?: { label?: string; value?: string }[]
  limit?: string
  tool_id?: string
}

export interface SceneResponse {
  scene_id: string
  collected_at: string
  start_at: string
  end_at: string
  platform: string
  mode: string
  band: string
  polarizations: string[]
  orbit_state: string
  incidence_angle: number
  bbox: BoundingBox
  preview_url: string | null
  thumbnail_url: string | null
  video_url: string | null
  assets_on_disk: string[]
  is_test_scene: boolean
  placeholder: boolean
  placeholder_note: string | null
  measurement: Measurement | null
  briefing_html: string | null
  overview_url: string | null
}

export interface MeasureJobAccepted {
  job_id: string
  status: "running"
}

export interface JobResult {
  measurement: Measurement | null
  briefing_html: string | null
  overview_url: string | null
}

export interface JobSnapshot {
  status: "idle" | "running" | "done" | "failed"
  step_index: number
  step_count: number
  sentence: string
  error: string | null
  result: JobResult | null
}

export interface CatalogItem {
  scene_id: string
  acquired_at: string | null
  satellite: string | null
  product_code: string | null
  mode: string | null
  incidence_angle: number | null
  orbit: string | null
  look: string | null
  place: string | null
  has_grd: boolean
  has_slc: boolean
  has_video: boolean
  bbox: BoundingBox | null
  cached: boolean
  thumbnail_url: string | null
  on_disk: boolean
}

export interface CatalogAsset {
  key: string
  title: string
  roles: string[]
  media_type: string
  bytes: number | null
  preview_default: boolean
  large: boolean
}

export interface CatalogItemDetail extends CatalogItem {
  assets: CatalogAsset[]
}

export interface CatalogSearchResponse {
  items: CatalogItem[]
  total: number
  offset: number
  limit: number
  indexed: number
  record_count: number
  indexing: boolean
  unread_for_bbox: number
  satellites: string[]
  products: string[]
}

export interface LibraryScene {
  scene_id: string
  collected_at: string
  platform: string
  mode: string
  assets_on_disk: string[]
  is_test_scene: boolean
  placeholder: boolean
  quicklook_url: string | null
  thumbnail_url: string | null
  video_url: string | null
}

export interface LibraryResponse {
  scenes: LibraryScene[]
}

export interface DownloadFile {
  key: string
  name: string
  state: "pending" | "downloading" | "done" | "kept" | "failed"
  bytes_done: number
  bytes_total: number
}

export interface DownloadSnapshot {
  status: "idle" | "running" | "done" | "failed"
  job_id: string | null
  scene_id: string | null
  files: DownloadFile[]
  error: string | null
}

export interface DownloadAccepted {
  job_id: string
  status: "running"
}

export interface AnalysisTool {
  id: string
  label: string
  category: string
  description: string
  locked: boolean
  reason: string
  needs_partner: boolean
  partners: string[]
  overview_url: string | null
  measurement: Measurement | null
  briefing_html: string | null
}

export interface AnalysisToolsResponse {
  tools: AnalysisTool[]
}
