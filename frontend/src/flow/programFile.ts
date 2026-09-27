// Download a strategy as a JSON file and load one back.
//
// The file is exactly the `m4ntis.strategy/v1` document the backend stores, so a
// downloaded program can be re-imported, compiled with `python -m tradecpu`, or
// shared with someone else.

import type { BlockEdge, BlockNode } from '../blocks/types.ts'
import { fromDocument, toDocument, type LoadedStrategy, type Viewport } from './serialize.ts'

export const PROGRAM_FILE_SUFFIX = '.m4ntis.json'
export const MAX_PROGRAM_FILE_BYTES = 1_000_000

export function programFileName(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `${slug || 'strategy'}${PROGRAM_FILE_SUFFIX}`
}

export function programFileText(name: string, nodes: BlockNode[], edges: BlockEdge[], viewport?: Viewport): string {
  return `${JSON.stringify(toDocument(name, nodes, edges, viewport), null, 2)}\n`
}

/** Parse file text into editor nodes and edges. Throws a message fit to show the user. */
export function parseProgramFile(text: string): LoadedStrategy {
  if (text.length > MAX_PROGRAM_FILE_BYTES) throw new Error('That file is too large to be a strategy.')
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    throw new Error('That file is not valid JSON.')
  }
  return fromDocument(raw)
}
