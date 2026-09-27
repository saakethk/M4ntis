import { API_BASE, id, postJson, record, str } from './http.ts'

export type User = {
  id: number
  email: string
}

const SESSION_TIMEOUT_MS = 5000

/** The signed-in user, or null when there is no valid session cookie. */
export async function getMe(): Promise<User | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), SESSION_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}/auth/me`, { credentials: 'include', signal: controller.signal })
    if (!response.ok) return null
    return readUser(await response.json())
  } catch {
    throw new Error('Could not reach the server.')
  } finally {
    clearTimeout(timer)
  }
}

export async function login(email: string, password: string): Promise<User> {
  return readUser(await postJson('/auth/login', { email, password }))
}

export async function register(email: string, password: string): Promise<User> {
  return readUser(await postJson('/auth/register', { email, password }))
}

export async function logout(): Promise<void> {
  await postJson('/auth/logout')
}

function readUser(body: unknown): User {
  const row = record(body, 'Account')
  return { id: id(row.id, 'Account'), email: str(row, 'email', 'Account') }
}
