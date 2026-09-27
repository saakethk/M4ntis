// Models the assistant panel can switch to. Gemini ids are Gemini Developer API
// model codes for generateContent (https://ai.google.dev/gemini-api/docs/models).
// 2.5 Flash stays the panel default. 3.8 Flash and 3.5 Flash-Lite are the current
// text models for new projects; 3.1 Pro is the stronger option.
// Meta ids are the Muse Spark models from https://ai.developer.meta.com/docs/models/
// called at https://api.meta.ai/v1/chat/completions. Contributor ids may be used for training.

export type AssistantModelChoice = {
  provider: 'gemini' | 'meta'
  model: string
  label: string
}

export const ASSISTANT_MODELS: readonly AssistantModelChoice[] = [
  { provider: 'gemini', model: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { provider: 'gemini', model: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { provider: 'gemini', model: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' },
  { provider: 'gemini', model: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
  { provider: 'gemini', model: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro' },
  { provider: 'meta', model: 'muse-spark-1.3', label: 'Muse Spark 1.3' },
  { provider: 'meta', model: 'muse-spark-1.3-contributor', label: 'Muse Spark 1.3 Contributor' },
  { provider: 'meta', model: 'muse-spark-1.2', label: 'Muse Spark 1.2' },
  { provider: 'meta', model: 'muse-spark-1.2-contributor', label: 'Muse Spark 1.2 Contributor' },
  { provider: 'meta', model: 'muse-spark-1.1', label: 'Muse Spark 1.1' },
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
