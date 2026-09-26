// Cookie session against the Mantis API. The session token stays in an
// HttpOnly cookie; this module never stores it or the password.

export type User = {
  id: number
  email: string
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001'

export async function getMe(): Promise<User | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), SESSION_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      credentials: 'include',
      signal: controller.signal,
    })
    if (response.status === 401 || !response.ok) return null
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
