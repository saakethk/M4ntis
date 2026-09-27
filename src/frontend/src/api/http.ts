// Shared fetch helpers. Every request sends the HttpOnly session cookie; this
// module never sees the token or the password beyond the request body.

import { resolveApiBase } from './apiBase.ts'

export const API_BASE = resolveApiBase(import.meta.env.VITE_API_URL, {
  dev: import.meta.env.DEV,
  pageHostname: typeof window === 'undefined' ? undefined : window.location.hostname,
})

const UNREACHABLE = 'Could not reach the server.'

/** Thrown for any non-2xx response. `status` lets callers treat 401 or 400 specially. */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (init.body != null && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  try {
    return await fetch(`${API_BASE}${path}`, { ...init, credentials: 'include', headers })
  } catch {
    throw new Error(UNREACHABLE)
  }
}

/** JSON body of a successful response, or an ApiError carrying the server's `detail`. */
export async function requestJson(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await request(path, init)
  const body = await readBody(response)
  if (!response.ok) throw new ApiError(errorMessage(body, response), response.status, body)
  return body
}

export function postJson(path: string, body?: unknown): Promise<unknown> {
  return requestJson(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}

export function putJson(path: string, body: unknown): Promise<unknown> {
  return requestJson(path, { method: 'PUT', body: JSON.stringify(body) })
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

/** FastAPI sends `detail` as a string, or as a list of validation errors. */
function errorMessage(body: unknown, response: Response): string {
  const detail = isRecord(body) ? body.detail : undefined
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (!isRecord(item) || typeof item.msg !== 'string') return ''
      const loc = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
      return loc ? `${loc}: ${item.msg}` : item.msg
    })
    const text = parts.filter(Boolean).join(' ')
    if (text) return text
  }
  return response.statusText || 'Request failed'
}

// Response readers. Each throws a short, user-facing message when the server
// sends something other than the documented shape.

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function record(value: unknown, what: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${what} response was not valid.`)
  return value
}

export function list(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${what} response was not valid.`)
  return value
}

export function str(row: Record<string, unknown>, key: string, what: string): string {
  const value = row[key]
  if (typeof value !== 'string') throw new Error(`${what} response was not valid.`)
  return value
}

export function num(row: Record<string, unknown>, key: string, what: string): number {
  const value = row[key]
  if (typeof value !== 'number') throw new Error(`${what} response was not valid.`)
  return value
}

export function optionalNum(row: Record<string, unknown>, key: string, what: string): number | null {
  return row[key] == null ? null : num(row, key, what)
}

export function optionalStr(row: Record<string, unknown>, key: string): string {
  return typeof row[key] === 'string' ? (row[key] as string) : ''
}

export function id(value: unknown, what: string): number {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) return value
  if (typeof value === 'string' && /^\d+$/.test(value)) return Number(value)
  throw new Error(`${what} response was not valid.`)
}
