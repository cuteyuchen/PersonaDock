const TOKEN_KEY = 'personadock.web.token'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export function readToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? ''
}

export function writeToken(token: string): void {
  const value = token.trim()
  if (value) sessionStorage.setItem(TOKEN_KEY, value)
  else sessionStorage.removeItem(TOKEN_KEY)
}

function requestHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra)
  const token = readToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

function errorMessage(detail: unknown, response: Response): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (typeof detail === 'object' && detail !== null && 'detail' in detail) {
    const value = (detail as { detail: unknown }).detail
    if (typeof value === 'string') return value
    if (typeof value === 'object' && value !== null && 'message' in value && typeof (value as { message: unknown }).message === 'string') {
      return String((value as { message: unknown }).message)
    }
    return JSON.stringify(value)
  }
  return `${response.status} ${response.statusText}`
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: unknown = null
  try {
    detail = await response.json()
  } catch {
    detail = await response.text().catch(() => '')
  }
  return new ApiError(response.status, errorMessage(detail, response), detail)
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: requestHeaders(init.headers),
  })
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path)
  },
  post<T>(path: string, body: unknown = {}): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
  put<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' })
  },
}
