import { api } from '@/api/client'
import type { JobRecord, ListResponse, PersonaRecord, RuntimeInstance } from '@/api/types'

export type JsonObject = Record<string, unknown>
export type ArtifactCategory = 'uploads' | 'exports' | 'backups' | 'keys'
export type RuntimeTarget = 'hermes' | 'openclaw'

export interface JobResult<T = JsonObject> {
  job: JobRecord
  result: T
}

export interface ArtifactItem {
  name: string
  path: string
  size: number
  modified_at?: string
}

export interface ArtifactList {
  category: ArtifactCategory
  roots: JsonObject
  items: ArtifactItem[]
  count: number
}

export interface ProviderRecord extends JsonObject {
  id: string
  name: string
  kind: string
  model: string
  base_url?: string | null
  has_secret?: boolean
}

export interface GenerationRecord extends JsonObject {
  id: string
  mode: string
  provider_id: string
  persona_id?: string | null
  requested_persona_id?: string | null
  status?: string
  created_at?: string
}

async function downloadArtifact(path: string): Promise<void> {
  const headers = new Headers()
  const token = sessionStorage.getItem('personadock.web.token') ?? ''
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`/api/v1/artifacts/download?path=${encodeURIComponent(path)}`, { headers })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const name = match?.[1] ?? path.split(/[\\/]/).pop() ?? 'personadock-artifact'
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

export const operationsApi = {
  personas: () => api.get<ListResponse<PersonaRecord>>('/api/v1/personas'),
  runtimes: async (): Promise<ListResponse<RuntimeInstance>> => {
    const items = await api.get<RuntimeInstance[]>('/api/instances')
    return { items, count: items.length }
  },

  artifacts: (category: ArtifactCategory) => api.get<ArtifactList>(`/api/v1/artifacts?category=${category}`),
  upload: (filename: string, contentBase64: string) => api.post<ArtifactItem>('/api/v1/uploads', { filename, content_base64: contentBase64 }),
  downloadArtifact,
  build: (personaId: string, targets: string[]) => api.post<JobResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/builds`, { targets }),
  pack: (personaId: string, targets: string[]) => api.post<JobResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/packages`, { targets }),
  publicExport: (personaId: string) => api.post<JobResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/public-export`),
  inspectPackage: (path: string) => api.post<JsonObject>('/api/v1/packages/inspect', { path }),
  keys: () => api.get<{ items: JsonObject[]; count: number }>('/api/v1/trust/keys'),
  createKey: (name: string) => api.post<JsonObject>('/api/v1/trust/keys', { name }),
  sign: (packagePath: string, keyId: string) => api.post<JobResult>('/api/v1/trust/signatures', { package_path: packagePath, key_id: keyId }),
  verify: (packagePath: string, signaturePath: string | null, trustLocalKeys = true) => api.post<JobResult>('/api/v1/trust/verify', { package_path: packagePath, signature_path: signaturePath || null, trust_local_keys: trustLocalKeys }),

  createBackup: (personaId: string, password: string) => api.post<JobResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/backups`, { password }),
  inspectBackup: (path: string) => api.post<JsonObject>('/api/v1/backups/inspect', { path }),
  restoreBackup: (path: string, password: string, folder: string) => api.post<JobResult>('/api/v1/backups/restore', { path, password, folder }),

  inspectCard: (path: string) => api.post<JsonObject>('/api/v1/character-cards/inspect', { path }),
  importCard: (path: string, folder: string, personaId: string | null, locale: string) => api.post<JobResult>('/api/v1/character-cards/import', { path, folder, persona_id: personaId || null, locale }),
  exportCard: (personaId: string, version: 2 | 3, charx: boolean) => api.post<JobResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/character-card`, { version, charx }),

  adapters: () => api.get<JsonObject>('/api/v1/adapters'),
  adapter: (name: string) => api.get<JsonObject>(`/api/v1/adapters/${encodeURIComponent(name)}`),
  doctor: (name: string, container: string | null, sshHost: string | null) => api.post<JobResult>(`/api/v1/adapters/${encodeURIComponent(name)}/doctor`, { container: container || null, ssh_host: sshHost || null }),
  skills: () => api.get<{ targets: string[]; scopes: string[] }>('/api/v1/skills'),
  skillPlan: (target: string, scope: string, personaId: string | null) => api.post<JsonObject>('/api/v1/skills/plan', { target, scope, persona_id: personaId || null }),
  skillInstall: (target: string, scope: string, personaId: string | null) => api.post<JobResult>('/api/v1/skills/install', { target, scope, persona_id: personaId || null }),

  adoptionPreview: (instanceId: string, personaId: string | null, name: string | null, destination: string | null, linkExisting: boolean) => api.post<JsonObject>('/api/v1/adoptions/preview', { instance_id: instanceId, persona_id: personaId || null, name: name || null, destination: destination || null, link_existing: linkExisting }),
  adopt: (instanceId: string, personaId: string | null, name: string | null, destination: string | null, linkExisting: boolean) => api.post<JobResult>('/api/v1/adoptions', { instance_id: instanceId, persona_id: personaId || null, name: name || null, destination: destination || null, link_existing: linkExisting }),
  deployments: () => api.get<{ items: JsonObject[]; count: number }>('/api/v1/deployments'),
  createDeploymentPlan: (payload: JsonObject) => api.post<JsonObject>('/api/v1/deployment-plans', payload),
  applyDeployment: (planId: string, confirmationToken: string) => api.post<JobResult>('/api/v1/deployments', { plan_id: planId, confirmation_token: confirmationToken }),
  rollbackDeployment: (deploymentId: string) => api.post<JobResult>(`/api/v1/deployments/${encodeURIComponent(deploymentId)}/rollback`, { confirmation: 'ROLLBACK' }),

  syncDashboard: (personaId: string) => api.get<JsonObject>(`/api/sync/${encodeURIComponent(personaId)}`),
  syncPolicy: (personaId: string) => api.get<JsonObject>(`/api/sync/${encodeURIComponent(personaId)}/policy`),
  updateSyncPolicy: (personaId: string, config: JsonObject) => api.put<JsonObject>(`/api/sync/${encodeURIComponent(personaId)}/policy`, { config, replace: true }),
  collectMemory: (personaId: string) => api.post<JobResult>(`/api/v1/governance/memory/${encodeURIComponent(personaId)}/collect`),
  memoryItems: (personaId: string) => api.get<JsonObject[]>(`/api/sync/${encodeURIComponent(personaId)}/memory`),
  approveMemory: (itemId: string, scope: string) => api.post<JsonObject>(`/api/sync/memory/${encodeURIComponent(itemId)}/approve`, { reviewer: 'vue', scope }),
  rejectMemory: (itemId: string, reason: string) => api.post<JsonObject>(`/api/sync/memory/${encodeURIComponent(itemId)}/reject`, { reviewer: 'vue', reason }),
  conflicts: (personaId: string) => api.get<JsonObject[]>(`/api/sync/${encodeURIComponent(personaId)}/conflicts`),
  resolveConflict: (conflictId: string, resolution: string) => api.post<JsonObject>(`/api/sync/conflicts/${encodeURIComponent(conflictId)}/resolve`, { resolution, reviewer: 'vue' }),
  syncPlan: (personaId: string) => api.get<JsonObject>(`/api/sync/${encodeURIComponent(personaId)}/plan`),
  applyMemory: (personaId: string, includeDefinitions: boolean) => api.post<JobResult>(`/api/v1/governance/memory/${encodeURIComponent(personaId)}/apply`, { confirmed: true, include_definitions: includeDefinitions }),
  syncRuns: (personaId: string) => api.get<JsonObject[]>(`/api/sync/${encodeURIComponent(personaId)}/runs`),
  propagation: (personaId: string) => api.get<JsonObject[]>(`/api/sync/${encodeURIComponent(personaId)}/propagation`),

  sessionDashboard: (personaId: string) => api.get<JsonObject>(`/api/sessions/${encodeURIComponent(personaId)}`),
  sessionPolicy: (personaId: string) => api.get<JsonObject>(`/api/sessions/${encodeURIComponent(personaId)}/policy`),
  updateSessionPolicy: (personaId: string, config: JsonObject) => api.put<JsonObject>(`/api/sessions/${encodeURIComponent(personaId)}/policy`, { config, replace: true }),
  collectSessions: (personaId: string) => api.post<JobResult>(`/api/v1/governance/sessions/${encodeURIComponent(personaId)}/collect`),
  sessionItems: (personaId: string) => api.get<JsonObject[]>(`/api/sessions/${encodeURIComponent(personaId)}/items`),
  addManualSession: (personaId: string, title: string, summary: string, pendingTasks: string[], sensitivity: string) => api.post<JsonObject>(`/api/sessions/${encodeURIComponent(personaId)}/manual`, { title, summary, pending_tasks: pendingTasks, emotional_context: {}, sensitivity }),
  approveSession: (summaryId: string, scope: string) => api.post<JsonObject>(`/api/session-summaries/${encodeURIComponent(summaryId)}/approve`, { reviewer: 'vue', scope }),
  rejectSession: (summaryId: string, reason: string) => api.post<JsonObject>(`/api/session-summaries/${encodeURIComponent(summaryId)}/reject`, { reviewer: 'vue', scope: 'local-only', reason }),
  sessionPlan: (personaId: string) => api.get<JsonObject>(`/api/sessions/${encodeURIComponent(personaId)}/plan`),
  applySessions: (personaId: string) => api.post<JobResult>(`/api/v1/governance/sessions/${encodeURIComponent(personaId)}/apply`, { confirmed: true }),

  providers: () => api.get<{ items: ProviderRecord[]; count: number }>('/api/v1/ai/providers'),
  createProvider: (payload: JsonObject) => api.post<ProviderRecord>('/api/v1/ai/providers', payload),
  updateProvider: (providerId: string, payload: JsonObject) => api.put<ProviderRecord>(`/api/v1/ai/providers/${encodeURIComponent(providerId)}`, payload),
  deleteProvider: (providerId: string) => api.delete<void>(`/api/v1/ai/providers/${encodeURIComponent(providerId)}`),
  testProvider: (providerId: string) => api.post<JsonObject>(`/api/v1/ai/providers/${encodeURIComponent(providerId)}/test`),
  providerModels: (providerId: string) => api.get<{ items: string[]; count: number }>(`/api/v1/ai/providers/${encodeURIComponent(providerId)}/models`),
  generations: () => api.get<{ items: GenerationRecord[]; count: number }>('/api/v1/ai/generations'),
  generation: (generationId: string) => api.get<GenerationRecord>(`/api/v1/ai/generations/${encodeURIComponent(generationId)}`),
  createGeneration: (payload: JsonObject) => api.post<JobResult<GenerationRecord>>('/api/v1/ai/generations', payload),
  applyGeneration: (generationId: string, folder: string | null) => api.post<JobResult>(`/api/v1/ai/generations/${encodeURIComponent(generationId)}/apply`, { confirmation: 'APPLY', folder: folder || null }),
}

export async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunk = 0x8000
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk))
  }
  return btoa(binary)
}
