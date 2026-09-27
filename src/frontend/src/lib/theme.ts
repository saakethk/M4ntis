// Light, dark, or follow the OS. The resolved theme lands on <html data-theme>, which the
// stylesheets key their tokens off; index.html applies the stored choice before React loads.

import { useSyncExternalStore } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'mantis.theme'
export const DARK_QUERY = '(prefers-color-scheme: dark)'

export type ThemeStorage = Pick<Storage, 'getItem' | 'setItem'>

const CYCLE: readonly ThemeChoice[] = ['light', 'dark', 'system']

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === 'light' || value === 'dark' || value === 'system'
}

export function resolveTheme(choice: ThemeChoice, prefersDark: boolean): ResolvedTheme {
  if (choice === 'system') return prefersDark ? 'dark' : 'light'
  return choice
}

/** The saved choice, or `system` when nothing usable is stored or storage is unreadable. */
export function readStoredTheme(storage: ThemeStorage | null = browserStorage()): ThemeChoice {
  try {
    const stored = storage?.getItem(THEME_STORAGE_KEY) ?? null
    return isThemeChoice(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function storeTheme(choice: ThemeChoice, storage: ThemeStorage | null = browserStorage()): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, choice)
  } catch {
    // Private browsing can reject writes; the theme still applies on this page.
  }
}

/** Light → Dark → System → Light. */
export function nextTheme(choice: ThemeChoice): ThemeChoice {
  return CYCLE[(CYCLE.indexOf(choice) + 1) % CYCLE.length]
}

export function themeLabel(choice: ThemeChoice): string {
  return choice === 'light' ? 'Light' : choice === 'dark' ? 'Dark' : 'System'
}

export function applyTheme(resolved: ResolvedTheme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
}

type ThemeState = { choice: ThemeChoice; resolved: ResolvedTheme }

let state: ThemeState | null = null
let media: MediaQueryList | null = null
const listeners = new Set<() => void>()

function darkQuery(): MediaQueryList | null {
  try {
    return typeof matchMedia === 'function' ? matchMedia(DARK_QUERY) : null
  } catch {
    return null
  }
}

function commit(choice: ThemeChoice): void {
  state = { choice, resolved: resolveTheme(choice, media?.matches ?? false) }
  applyTheme(state.resolved)
  for (const listener of listeners) listener()
}

function onSystemChange(): void {
  if (state?.choice === 'system') commit('system')
}

function current(): ThemeState {
  if (!state) {
    media = darkQuery()
    media?.addEventListener('change', onSystemChange)
    commit(readStoredTheme())
  }
  return state as ThemeState
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function setTheme(choice: ThemeChoice): void {
  current()
  storeTheme(choice)
  commit(choice)
}

/** The user's choice plus the theme it resolves to right now. */
export function useTheme(): ThemeState & { setTheme: (choice: ThemeChoice) => void } {
  const snapshot = useSyncExternalStore(subscribe, current)
  return { ...snapshot, setTheme }
}

export function useResolvedTheme(): ResolvedTheme {
  return useSyncExternalStore(subscribe, () => current().resolved)
}

function browserStorage(): ThemeStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}
