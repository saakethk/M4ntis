// Models the assistant panel can switch to. Gemini ids are Gemini API model codes.
// Meta ids are Llama API model ids for https://api.llama.com/compat/v1.

export type AssistantModelChoice = {
  provider: 'gemini' | 'meta'
  model: string
  label: string
}

export const ASSISTANT_MODELS: readonly AssistantModelChoice[] = [
  { provider: 'gemini', model: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
  { provider: 'gemini', model: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { provider: 'gemini', model: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { provider: 'meta', model: 'Llama-3.3-70B-Instruct', label: 'Llama 3.3 70B' },
  { provider: 'meta', model: 'Llama-3.3-8B-Instruct', label: 'Llama 3.3 8B' },
]

export const DEFAULT_ASSISTANT_MODEL = ASSISTANT_MODELS[0]

export const ASSISTANT_MODEL_STORAGE_KEY = 'mantis.assistant.model'

export type ModelStorage = {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function modelChoiceId(choice: { provider: string; model: string }): string {
  return `${choice.provider}:${choice.model}`
}

export function findAssistantModel(id: string | null | undefined): AssistantModelChoice {
  return ASSISTANT_MODELS.find((choice) => modelChoiceId(choice) === id) ?? DEFAULT_ASSISTANT_MODEL
}

export function readStoredAssistantModel(storage?: ModelStorage | null): AssistantModelChoice {
  const store = storage === undefined ? browserStorage() : storage
  if (!store) return DEFAULT_ASSISTANT_MODEL
  try {
    return findAssistantModel(store.getItem(ASSISTANT_MODEL_STORAGE_KEY))
  } catch {
    return DEFAULT_ASSISTANT_MODEL
  }
}

export function storeAssistantModel(choice: AssistantModelChoice, storage?: ModelStorage | null): void {
  const store = storage === undefined ? browserStorage() : storage
  if (!store) return
  try {
    store.setItem(ASSISTANT_MODEL_STORAGE_KEY, modelChoiceId(choice))
  } catch {
    // Private browsing can reject writes. The choice still applies on this page.
  }
}

function browserStorage(): ModelStorage | null {
  try {
    if (typeof localStorage === 'undefined') return null
    return localStorage
  } catch {
    return null
  }
}
