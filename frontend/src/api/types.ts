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

export interface BindingRecord {
  id: string
  persona_id: string
  runtime_instance_id: string
  adopted: boolean
  sync_policy_id: string | null
  last_deployed_version: string | null
  managed_since: string
  last_synced_at: string | null
}

export interface PersonaDetail extends PersonaRecord {
  bindings: BindingRecord[]
}

export interface PersonaRoots {
  default_root: string
  roots: string[]
  environment: string
}

export interface CanonicalPersona {
  schema_version: 3
  id: string
  version: string
  name: string
  locale: string
  summary: string
  identity: {
    statement: string
    core_traits: string[]
  }
  voice: {
    style: string
    principles: string[]
  }
  boundaries: Array<Record<string, unknown>>
  behaviors: Array<Record<string, unknown>>
  budgets: {
    target_chars: number
    hard_limit_chars: number
  }
  memory: Record<string, unknown>
  targets: string[]
  [key: string]: unknown
}

export interface CanonicalResponse {
  model: CanonicalPersona
  content_hash: string
}

export interface RevisionRecord {
  revision_id: string
  persona_id: string
  parent_revision_id: string | null
  created_at: string
  source: string
  summary: string
  content_hash: string
  validation_result: Record<string, unknown>
  test_result: Record<string, unknown>
}

export interface RevisionListResponse {
  current_hash: string
  items: RevisionRecord[]
  count: number
}

export interface DiffRisk {
  level: 'none' | 'low' | 'medium' | 'high' | 'destructive' | string
  reasons: string[]
}

export interface PersonaDiff {
  changed: boolean
  before_hash: string
  after_hash: string
  risk: DiffRisk
  field_changes?: Array<Record<string, unknown>>
  added_boundaries?: Array<Record<string, unknown>>
  removed_boundaries?: Array<Record<string, unknown>>
  changed_boundaries?: Array<Record<string, unknown>>
  added_behaviors?: Array<Record<string, unknown>>
  removed_behaviors?: Array<Record<string, unknown>>
  changed_behaviors?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export interface ValidationResult {
  ok: boolean
  errors: string[]
}

export interface PersonaTestResult {
  ok: boolean
  total?: number
  passed?: number
  failed?: number
  results?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export interface CompilePreview {
  soul: string
  skill: string
  soul_chars: number
  target_chars: number | null
  hard_limit_chars: number | null
  targets: string[]
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
