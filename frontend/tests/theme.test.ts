import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  THEME_STORAGE_KEY,
  isThemeChoice,
  nextTheme,
  readStoredTheme,
  resolveTheme,
  storeTheme,
  themeLabel,
  type ThemeStorage,
} from '../src/lib/theme.ts'

function memoryStorage(initial: Record<string, string> = {}): ThemeStorage & { data: Record<string, string> } {
  const data = { ...initial }
  return {
    data,
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => {
      data[key] = value
    },
  }
}

const throwing: ThemeStorage = {
  getItem: () => {
    throw new Error('blocked')
  },
  setItem: () => {
    throw new Error('blocked')
  },
}

describe('resolveTheme', () => {
  it('uses an explicit choice regardless of the OS preference', () => {
    assert.equal(resolveTheme('light', true), 'light')
    assert.equal(resolveTheme('dark', false), 'dark')
  })

  it('follows the OS preference for system', () => {
    assert.equal(resolveTheme('system', true), 'dark')
    assert.equal(resolveTheme('system', false), 'light')
  })
})

describe('readStoredTheme', () => {
  it('reads a saved choice', () => {
    assert.equal(readStoredTheme(memoryStorage({ [THEME_STORAGE_KEY]: 'dark' })), 'dark')
    assert.equal(readStoredTheme(memoryStorage({ [THEME_STORAGE_KEY]: 'light' })), 'light')
    assert.equal(readStoredTheme(memoryStorage({ [THEME_STORAGE_KEY]: 'system' })), 'system')
  })

  it('defaults to system when nothing usable is stored', () => {
    assert.equal(readStoredTheme(memoryStorage()), 'system')
    assert.equal(readStoredTheme(memoryStorage({ [THEME_STORAGE_KEY]: 'sepia' })), 'system')
    assert.equal(readStoredTheme(null), 'system')
  })

  it('defaults to system when storage throws', () => {
    assert.equal(readStoredTheme(throwing), 'system')
  })
})

describe('storeTheme', () => {
  it('saves under the theme key', () => {
    const storage = memoryStorage()
    storeTheme('dark', storage)
    assert.equal(storage.data[THEME_STORAGE_KEY], 'dark')
    assert.equal(readStoredTheme(storage), 'dark')
  })

  it('ignores storage that rejects writes', () => {
    assert.doesNotThrow(() => storeTheme('light', throwing))
    assert.doesNotThrow(() => storeTheme('light', null))
  })
})

describe('theme choices', () => {
  it('cycles light, dark, system', () => {
    assert.equal(nextTheme('light'), 'dark')
    assert.equal(nextTheme('dark'), 'system')
    assert.equal(nextTheme('system'), 'light')
  })

  it('recognises only the three choices', () => {
    for (const value of ['light', 'dark', 'system']) assert.ok(isThemeChoice(value))
    for (const value of ['', 'Dark', null, undefined, 1]) assert.ok(!isThemeChoice(value))
  })

  it('labels each choice', () => {
    assert.equal(themeLabel('light'), 'Light')
    assert.equal(themeLabel('dark'), 'Dark')
    assert.equal(themeLabel('system'), 'System')
  })
})
