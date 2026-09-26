// Cookie session against the Mantis API. The session token stays in an
// HttpOnly cookie; this module never stores it or the password.

import { resolveApiBase } from './apiBase.ts'

export type User = {
  id: number
  email: string
}

const SESSION_TIMEOUT_MS = 5000

const API_BASE = resolveApiBase(import.meta.env.VITE_API_URL, {
  dev: import.meta.env.DEV,
  pageHostname: typeof window === 'undefined' ? undefined : window.location.hostname,
})

export async function getMe(): Promise<User | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), SESSION_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      credentials: 'include',
      signal: controller.signal,
    })
    // No session cookie yet. That is signed out, not a failed request.
    if (response.status === 401) return null
    if (!response.ok) return null
    return (await response.json()) as User
  } catch {
    throw new Error('Could not reach the server.')
  } finally {
    clearTimeout(timer)
  }
}

export function login(email: string, password: string): Promise<User> {
  return postAuth('/auth/login', email, password)
}

export function register(email: string, password: string): Promise<User> {
  return postAuth('/auth/register', email, password)
}

export async function logout(): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
  } catch {
    throw new Error('Could not reach the server.')
  }
  if (!response.ok) throw new Error(await errorMessage(response))
}

async function postAuth(path: string, email: string, password: string): Promise<User> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  } catch {
    throw new Error('Could not reach the server.')
  }
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as User
}

export type StrategySummary = {
  id: number
  name: string
  visibility: string
  updated_at: string
}

export type StrategyRecord = {
  id: number
  name: string
  document: unknown
  ir: unknown
}

export type StrategyWrite = {
  name: string
  document: unknown
  ir: unknown
  visibility: 'private'
}

export function listStrategies(): Promise<StrategySummary[]> {
  return requestJson('/strategies').then((body) => {
    if (!Array.isArray(body)) throw new Error('Could not load strategies.')
    return body.map(readSummary)
  })
}

export function getStrategy(id: number): Promise<StrategyRecord> {
  return requestJson(`/strategies/${id}`).then(readRecord)
}

export function createStrategy(body: StrategyWrite): Promise<StrategyRecord> {
  return requestJson('/strategies', {
    method: 'POST',
    body: JSON.stringify(body),
  }).then(readRecord)
}

export function updateStrategy(id: number, body: StrategyWrite): Promise<StrategyRecord> {
  return requestJson(`/strategies/${id}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  }).then(readRecord)
}

async function requestJson(path: string, init: RequestInit = {}): Promise<unknown> {
  const headers = new Headers(init.headers)
  if (init.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers,
    })
  } catch {
    throw new Error('Could not reach the server.')
  }
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

function readSummary(body: unknown): StrategySummary {
  const record = readRecord(body)
  const row = body as { visibility?: unknown; updated_at?: unknown }
  return {
    id: record.id,
    name: record.name,
    visibility: typeof row.visibility === 'string' ? row.visibility : 'private',
    updated_at: typeof row.updated_at === 'string' ? row.updated_at : '',
  }
}

function readRecord(body: unknown): StrategyRecord {
  if (!body || typeof body !== 'object') throw new Error('Strategy response was not valid.')
  const row = body as { id?: unknown; name?: unknown; document?: unknown; ir?: unknown }
  if (typeof row.name !== 'string') throw new Error('Strategy response was not valid.')
  return {
    id: readId(row.id),
    name: row.name,
    document: row.document,
    ir: row.ir,
  }
}

function readId(value: unknown): number {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) return value
  if (typeof value === 'string' && /^\d+$/.test(value)) return Number(value)
  throw new Error('Strategy response was not valid.')
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) return body.detail
    if (Array.isArray(body.detail)) {
      const parts = body.detail
        .map((item) => {
          if (typeof item === 'string') return item
          if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') {
            return item.msg
          }
          return ''
        })
        .filter(Boolean)
      if (parts.length > 0) return parts.join(' ')
    }
  } catch {
    // Response was not JSON.
  }
  return response.statusText || 'Request failed'
}
