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

export type AssistantProgram = {
  resolution: string
  symbol: string
  fast: number
  slow: number
  quantity: number
}

export type AssistantReply = {
  reply: string
  dummy: boolean
  program: AssistantProgram | null
}

export type BacktestOrder = {
  symbol: string
  side: string
  quantity: number
  price: number
}

export type BacktestBalance = {
  cash: number
  equity: number
}

export type BacktestResult = {
  id: number
  dummy: boolean
  orders: BacktestOrder[]
  balances: BacktestBalance[]
}

export type BacktestMenu = {
  dummy: boolean
  equity: number
  returnPct: number
  orders: BacktestOrder[]
  balances: BacktestBalance[]
}

export function getDummyBacktest(): Promise<BacktestMenu> {
  return requestJson('/backtests/dummy').then(readBacktestMenu)
}

function readBacktestMenu(body: unknown): BacktestMenu {
  const result = readBacktest({ ...(body as object), id: 1 })
  if (!body || typeof body !== 'object') throw new Error('Backtest response was not valid.')
  const row = body as { equity?: unknown; return_pct?: unknown }
  if (typeof row.equity !== 'number' || typeof row.return_pct !== 'number') {
    throw new Error('Backtest response was not valid.')
  }
  return {
    dummy: result.dummy,
    equity: row.equity,
    returnPct: row.return_pct,
    orders: result.orders,
    balances: result.balances,
  }
}

export function runDummyBacktest(userId: number, strategyId: number): Promise<BacktestResult> {
  return requestJson('/backtests', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, strategy_id: strategyId }),
  }).then(readBacktest)
}

function readBacktest(body: unknown): BacktestResult {
  if (!body || typeof body !== 'object') throw new Error('Backtest response was not valid.')
  const row = body as { id?: unknown; dummy?: unknown; orders?: unknown; balances?: unknown }
  if (!Array.isArray(row.orders) || !Array.isArray(row.balances)) {
    throw new Error('Backtest response was not valid.')
  }
  return {
    id: readId(row.id),
    dummy: row.dummy === true,
    orders: row.orders.map(readOrder),
    balances: row.balances.map(readBalance),
  }
}

function readOrder(body: unknown): BacktestOrder {
  if (!body || typeof body !== 'object') throw new Error('Backtest response was not valid.')
  const row = body as { symbol?: unknown; side?: unknown; quantity?: unknown; price?: unknown }
  if (typeof row.symbol !== 'string' || typeof row.side !== 'string') {
    throw new Error('Backtest response was not valid.')
  }
  if (typeof row.quantity !== 'number' || typeof row.price !== 'number') {
    throw new Error('Backtest response was not valid.')
  }
  return { symbol: row.symbol, side: row.side, quantity: row.quantity, price: row.price }
}

function readBalance(body: unknown): BacktestBalance {
  if (!body || typeof body !== 'object') throw new Error('Backtest response was not valid.')
  const row = body as { cash?: unknown; equity?: unknown }
  if (typeof row.cash !== 'number' || typeof row.equity !== 'number') {
    throw new Error('Backtest response was not valid.')
  }
  return { cash: row.cash, equity: row.equity }
}

export type DiscussionPost = {
  id: number
  userId: number
  author: string
  body: string
  strategyId: number | null
  strategyName: string | null
  parentId: number | null
  likesCount: number
  createdAt: string
  liked: boolean
}

export type DiscussionCreated = {
  id: number
  strategyId: number | null
  strategyMadePublic: boolean
}

export function listDiscussions(): Promise<DiscussionPost[]> {
  return requestJson('/discussions').then((body) => {
    if (!Array.isArray(body)) throw new Error('Could not load discussions.')
    return body.map(readDiscussion)
  })
}

export function createDiscussion(body: {
  body: string
  strategyId?: number
  parentId?: number
}): Promise<DiscussionCreated> {
  return requestJson('/discussions', {
    method: 'POST',
    body: JSON.stringify({
      body: body.body,
      ...(body.strategyId != null ? { strategy_id: body.strategyId } : {}),
      ...(body.parentId != null ? { parent_id: body.parentId } : {}),
    }),
  }).then(readDiscussionCreated)
}

export function likeDiscussion(postId: number): Promise<{ id: number; likesCount: number; liked: boolean }> {
  return requestJson(`/discussions/${postId}/like`, { method: 'POST' }).then((body) => {
    if (!body || typeof body !== 'object') throw new Error('Discussion response was not valid.')
    const row = body as { id?: unknown; likes_count?: unknown; liked?: unknown }
    return {
      id: readId(row.id),
      likesCount: typeof row.likes_count === 'number' ? row.likes_count : 0,
      liked: row.liked === true,
    }
  })
}

function readDiscussion(body: unknown): DiscussionPost {
  if (!body || typeof body !== 'object') throw new Error('Discussion response was not valid.')
  const row = body as {
    id?: unknown
    user_id?: unknown
    author?: unknown
    body?: unknown
    strategy_id?: unknown
    strategy_name?: unknown
    parent_id?: unknown
    likes_count?: unknown
    created_at?: unknown
    liked?: unknown
  }
  if (typeof row.body !== 'string' || typeof row.author !== 'string') {
    throw new Error('Discussion response was not valid.')
  }
  return {
    id: readId(row.id),
    userId: readId(row.user_id),
    author: row.author,
    body: row.body,
    strategyId: row.strategy_id == null ? null : readId(row.strategy_id),
    strategyName: typeof row.strategy_name === 'string' && row.strategy_name.trim() ? row.strategy_name : null,
    parentId: row.parent_id == null ? null : readId(row.parent_id),
    likesCount: typeof row.likes_count === 'number' ? row.likes_count : 0,
    createdAt: typeof row.created_at === 'string' ? row.created_at : '',
    liked: row.liked === true,
  }
}

function readDiscussionCreated(body: unknown): DiscussionCreated {
  if (!body || typeof body !== 'object') throw new Error('Discussion response was not valid.')
  const row = body as { id?: unknown; strategy_id?: unknown; strategy_made_public?: unknown }
  return {
    id: readId(row.id),
    strategyId: row.strategy_id == null ? null : readId(row.strategy_id),
    strategyMadePublic: row.strategy_made_public === true,
  }
}

export function askAssistant(prompt: string): Promise<AssistantReply> {
  return requestJson('/llm', {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  }).then(readAssistantReply)
}

function readAssistantReply(body: unknown): AssistantReply {
  if (!body || typeof body !== 'object') throw new Error('Assistant response was not valid.')
  const row = body as { reply?: unknown; dummy?: unknown; program?: unknown }
  if (typeof row.reply !== 'string' || !row.reply.trim()) {
    throw new Error('Assistant response was not valid.')
  }
  return { reply: row.reply, dummy: row.dummy === true, program: readProgram(row.program) }
}

function readProgram(body: unknown): AssistantProgram | null {
  if (body == null) return null
  if (!body || typeof body !== 'object') throw new Error('Assistant response was not valid.')
  const row = body as {
    resolution?: unknown
    symbol?: unknown
    fast?: unknown
    slow?: unknown
    quantity?: unknown
  }
  if (typeof row.resolution !== 'string' || typeof row.symbol !== 'string') {
    throw new Error('Assistant response was not valid.')
  }
  if (typeof row.fast !== 'number' || typeof row.slow !== 'number' || typeof row.quantity !== 'number') {
    throw new Error('Assistant response was not valid.')
  }
  return {
    resolution: row.resolution,
    symbol: row.symbol,
    fast: row.fast,
    slow: row.slow,
    quantity: row.quantity,
  }
}

export function updateStrategy(id: number, body: StrategyWrite): Promise<StrategyRecord> {
  return requestJson(`/strategies/${id}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  }).then(readRecord)
}

export type CompileDiagnostic = {
  level: string
  message: string
  node?: string
}

export type CompileResult = {
  ok: boolean
  asm: string
  detail: string
  diagnostics: CompileDiagnostic[]
}

export async function compileStrategy(document: unknown): Promise<CompileResult> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/compile`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(document),
    })
  } catch {
    throw new Error('Could not reach the server.')
  }
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  // A rejected strategy is 400 with diagnostics. Other failures have no program to show.
  if (!response.ok && response.status !== 400) {
    throw new Error(compileDetail(body) || response.statusText || 'Could not compile')
  }
  return readCompile(body)
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

function readCompile(body: unknown): CompileResult {
  if (!body || typeof body !== 'object') throw new Error('Compile response was not valid.')
  const row = body as { ok?: unknown; asm?: unknown; detail?: unknown; diagnostics?: unknown }
  return {
    ok: row.ok === true,
    asm: typeof row.asm === 'string' ? row.asm : '',
    detail: compileDetail(body),
    diagnostics: Array.isArray(row.diagnostics) ? row.diagnostics.map(readDiagnostic) : [],
  }
}

function readDiagnostic(body: unknown): CompileDiagnostic {
  if (!body || typeof body !== 'object') throw new Error('Compile response was not valid.')
  const row = body as { level?: unknown; message?: unknown; node?: unknown }
  if (typeof row.message !== 'string') throw new Error('Compile response was not valid.')
  return {
    level: typeof row.level === 'string' ? row.level : 'error',
    message: row.message,
    ...(typeof row.node === 'string' ? { node: row.node } : {}),
  }
}

function compileDetail(body: unknown): string {
  if (!body || typeof body !== 'object') return ''
  const detail = (body as { detail?: unknown }).detail
  return typeof detail === 'string' ? detail : ''
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
