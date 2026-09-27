// Remember the user's assistant model between visits.

import type { ModelChoice } from '../../api/assistant.ts'

export const MODEL_STORAGE_KEY = 'mantis.assistant.model'

export type ModelStorage = Pick<Storage, 'getItem' | 'setItem'>

export function choiceId(choice: { provider: string; model: string }): string {
  return `${choice.provider}:${choice.model}`
}

/**
 * The model to preselect: the stored choice if it is still offered and usable, then the
 * server default, then the first usable model, then the first listed.
 */
export function initialChoice(
  models: ModelChoice[],
  serverDefault: { provider: string; model: string } | null,
  storage: ModelStorage | null = browserStorage(),
): ModelChoice | null {
  const usable = models.filter((m) => m.available)
  const find = (id: string | null) => usable.find((m) => choiceId(m) === id)
  let stored: string | null = null
  try {
    stored = storage?.getItem(MODEL_STORAGE_KEY) ?? null
  } catch {
    stored = null
  }
  return find(stored) ?? (serverDefault ? find(choiceId(serverDefault)) : undefined) ?? usable[0] ?? models[0] ?? null
}

export function rememberChoice(choice: ModelChoice, storage: ModelStorage | null = browserStorage()): void {
  try {
    storage?.setItem(MODEL_STORAGE_KEY, choiceId(choice))
  } catch {
    // Private browsing can reject writes; the choice still applies on this page.
  }
}

function browserStorage(): ModelStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}
