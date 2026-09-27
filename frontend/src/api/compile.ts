import { ApiError, isRecord, list, postJson, record, str } from './http.ts'

export type CompileDiagnostic = {
  level: 'error' | 'warning' | 'info'
  message: string
  /** Editor block to highlight. */
  node?: string
}

export type CompileResult = {
  ok: boolean
  diagnostics: CompileDiagnostic[]
  /** Program size in 16-bit words when it compiled. */
  words: number | null
}

/** Compile a strategy document. A rejected strategy resolves with `ok: false` and its diagnostics. */
export async function compileStrategy(document: unknown): Promise<CompileResult> {
  try {
    return readResult(await postJson('/compile', document))
  } catch (error) {
    if (error instanceof ApiError && error.status === 400 && isRecord(error.body) && 'diagnostics' in error.body) {
      return readResult(error.body)
    }
    throw error
  }
}

function readResult(body: unknown): CompileResult {
  const row = record(body, 'Compile')
  const manifest = isRecord(row.manifest) ? row.manifest : null
  const words = manifest && Array.isArray(manifest.words) ? manifest.words.length : null
  return {
    ok: row.ok === true,
    diagnostics: list(row.diagnostics ?? [], 'Compile').map(readDiagnostic),
    words,
  }
}

function readDiagnostic(body: unknown): CompileDiagnostic {
  const row = record(body, 'Compile')
  const level = row.level === 'warning' || row.level === 'info' ? row.level : 'error'
  return {
    level,
    message: str(row, 'message', 'Compile'),
    ...(typeof row.node === 'string' ? { node: row.node } : {}),
  }
}
