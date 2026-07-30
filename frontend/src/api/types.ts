export interface NavigationItem {
  id: string
  label: string
  route: string
  phase: number
}

export interface CapabilitySummary {
  total: number
  ready: number
  legacy: number
  planned: number
}

export interface MetaResponse {
  product: string
  version: string
  api_version: number
  web_control_plane: number
  web_refactor_phase: number
  frontend?: string
  control_plane: string
  capabilities: CapabilitySummary
  navigation: NavigationItem[]
}

export interface PersonaRecord {
  id: string
  name: string
  version: string
  schema_version: number
  summary: string
  source_path: string | null
  created_at: string
  updated_at: string
}

export interface RuntimeInstance {
  id: string
  adapter: string
  transport: string
  platform_instance_id: string
  display_name: string
  location: string
  managed: boolean
  capabilities: Record<string, unknown>
  metadata: Record<string, unknown>
  first_seen_at: string
  last_seen_at: string
}

export type JobStatus = 'queued' | 'running' | 'waiting-review' | 'success' | 'failed' | 'cancelled'

export interface JobRecord {
  id: string
  kind: string
  label: string
  status: JobStatus
  progress: number
  persona_id: string | null
  runtime_instance_id: string | null
  input: Record<string, unknown>
  output: Record<string, unknown> | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface DashboardResponse {
  registry: Record<string, number>
  metrics: {
    personas: number
    runtime_instances: number
    managed_instances: number
    unmanaged_instances: number
    active_jobs: number
    failed_jobs: number
  }
  personas: PersonaRecord[]
  instances: RuntimeInstance[]
  jobs: JobRecord[]
}

export interface ListResponse<T> {
  items: T[]
  count: number
}
