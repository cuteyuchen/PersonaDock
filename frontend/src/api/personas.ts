import { api } from '@/api/client'
import type {
  CanonicalPersona,
  CanonicalResponse,
  CompilePreview,
  ListResponse,
  PersonaDetail,
  PersonaDiff,
  PersonaRecord,
  PersonaRoots,
  PersonaTestResult,
  RevisionListResponse,
  RevisionRecord,
  ValidationResult,
} from '@/api/types'

export interface PersonaCreateInput {
  id: string
  name: string
  locale: string
  folder?: string
}

export interface PersonaCreateResult {
  project: string
  persona: PersonaRecord
}

export interface CanonicalSaveResult {
  model: CanonicalPersona
  revision: RevisionRecord
  diff: PersonaDiff
  validation: ValidationResult
  tests: PersonaTestResult
}

export const personasApi = {
  list: () => api.get<ListResponse<PersonaRecord>>('/api/v1/personas'),
  roots: () => api.get<PersonaRoots>('/api/v1/persona-roots'),
  get: (personaId: string) => api.get<PersonaDetail>(`/api/v1/personas/${encodeURIComponent(personaId)}`),
  create: (input: PersonaCreateInput) => api.post<PersonaCreateResult>('/api/v1/personas', input),
  register: (path: string) => api.post<PersonaCreateResult>('/api/v1/personas/register', { path }),
  canonical: (personaId: string) => api.get<CanonicalResponse>(`/api/v1/personas/${encodeURIComponent(personaId)}/canonical`),
  saveCanonical: (personaId: string, model: CanonicalPersona, contentHash: string, summary: string) =>
    api.put<CanonicalSaveResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/canonical`, {
      model,
      expected_content_hash: contentHash,
      summary,
      source: 'manual',
    }),
  revisions: (personaId: string) => api.get<RevisionListResponse>(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions`),
  revision: (personaId: string, revisionId: string) =>
    api.get<{ revision: RevisionRecord; model: CanonicalPersona }>(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions/${encodeURIComponent(revisionId)}`),
  diff: (personaId: string, beforeRevisionId: string | null, afterRevisionId: string | null) =>
    api.post<PersonaDiff>(`/api/v1/personas/${encodeURIComponent(personaId)}/diff`, {
      before_revision_id: beforeRevisionId,
      after_revision_id: afterRevisionId,
    }),
  restorePreview: (personaId: string, revisionId: string) =>
    api.post<{ plan: Record<string, unknown>; diff: PersonaDiff }>(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions/${encodeURIComponent(revisionId)}/restore/preview`),
  restore: (personaId: string, revisionId: string, planHash: string, summary: string) =>
    api.post<{ model: CanonicalPersona; revision: RevisionRecord; tests: PersonaTestResult }>(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions/${encodeURIComponent(revisionId)}/restore`, {
      plan_hash: planHash,
      summary,
    }),
  validate: (personaId: string) => api.get<ValidationResult>(`/api/v1/personas/${encodeURIComponent(personaId)}/validation`),
  test: (personaId: string) => api.post<{ result: PersonaTestResult }>(`/api/v1/personas/${encodeURIComponent(personaId)}/tests`),
  compilePreview: (personaId: string) => api.get<CompilePreview>(`/api/v1/personas/${encodeURIComponent(personaId)}/compile-preview`),
  migratePreview: (personaId: string) => api.post<Record<string, unknown>>(`/api/v1/personas/${encodeURIComponent(personaId)}/migrate-v3`, { dry_run: true, backup: true }),
  migrate: (personaId: string) => api.post<Record<string, unknown>>(`/api/v1/personas/${encodeURIComponent(personaId)}/migrate-v3`, { dry_run: false, backup: true }),
}
