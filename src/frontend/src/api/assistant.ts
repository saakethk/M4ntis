import { readAssistantGraph, type AssistantGraph } from '../flow/assistantGraph.ts'
import { list, postJson, record, requestJson, str } from './http.ts'

export type ModelChoice = {
  provider: string
  model: string
  label: string
  /** The server has an API key for this provider. */
  available: boolean
}

export type ModelList = {
  models: ModelChoice[]
  /** The server's configured default, when it is one of the listed models. */
  defaultChoice: { provider: string; model: string } | null
}

export type ChatTurn = {
  role: 'user' | 'assistant'
  content: string
}

/** One tool call the agent made while answering. */
export type AgentStep = {
  tool: string
  ok: boolean
  detail: string
}

export type AssistantReply = {
  reply: string
  /** The edited canvas, or null when the agent changed nothing. */
  graph: AssistantGraph | null
  steps: AgentStep[]
  model: string | null
}

export async function listAssistantModels(): Promise<ModelList> {
  const row = record(await requestJson('/llm/models'), 'Model list')
  const fallback = row.default && typeof row.default === 'object' ? (row.default as Record<string, unknown>) : null
  return {
    models: list(row.models, 'Model list').map((item) => {
      const choice = record(item, 'Model list')
      return {
        provider: str(choice, 'provider', 'Model list'),
        model: str(choice, 'model', 'Model list'),
        label: str(choice, 'label', 'Model list'),
        available: choice.available === true,
      }
    }),
    defaultChoice:
      fallback && typeof fallback.provider === 'string' && typeof fallback.model === 'string'
        ? { provider: fallback.provider, model: fallback.model }
        : null,
  }
}

export async function askAssistant(request: {
  prompt: string
  graph: AssistantGraph
  history: ChatTurn[]
  choice: { provider: string; model: string } | null
}): Promise<AssistantReply> {
  const body = await postJson('/llm', {
    prompt: request.prompt,
    graph: request.graph,
    history: request.history,
    ...(request.choice ? { provider: request.choice.provider, model: request.choice.model } : {}),
  })
  const row = record(body, 'Assistant')
  const reply = str(row, 'reply', 'Assistant')
  if (!reply.trim()) throw new Error('Assistant response was not valid.')
  return {
    reply,
    graph: readAssistantGraph(row.graph),
    steps: list(row.steps ?? [], 'Assistant').map((item) => {
      const step = record(item, 'Assistant')
      return { tool: str(step, 'tool', 'Assistant'), ok: step.ok === true, detail: typeof step.detail === 'string' ? step.detail : '' }
    }),
    model: typeof row.model === 'string' ? row.model : null,
  }
}
