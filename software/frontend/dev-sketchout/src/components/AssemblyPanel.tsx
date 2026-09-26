import { useEffect, useState } from 'react';
import { PROGRAM_WORDS } from '../blocks/hardware';

interface CompilerDiagnostic {
  level: 'error' | 'warning' | 'info';
  message: string;
  node?: string;
}

interface Manifest {
  resolution: string;
  barMinutes: number;
  historyTicks: number;
  warmupTicks: number;
  programWords: number;
  buffers: { buf: number; symbol: string | null; priceExponent: number; used: boolean }[];
  variableSlots: { user: string[]; loopCounters: Record<string, string> };
}

type CompileResponse =
  | { ok: true; asm: string; hex: string; manifest: Manifest; diagnostics: CompilerDiagnostic[] }
  | { ok: false; diagnostics: CompilerDiagnostic[] };

type State = { status: 'idle' } | { status: 'done'; result: CompileResponse; source: string };

function download(text: string, filename: string, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  Object.assign(document.createElement('a'), { href: url, download: filename }).click();
  URL.revokeObjectURL(url);
}

/** Compiles the current strategy document through the dev server's `/api/compile` whenever it changes. */
export function AssemblyPanel({
  documentJson,
  slug,
  onFocusNode,
}: {
  documentJson: string;
  slug: string;
  onFocusNode: (id: string) => void;
}) {
  const [state, setState] = useState<State>({ status: 'idle' });

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch('/api/compile', { method: 'POST', body: documentJson, signal: ctrl.signal });
        const result: CompileResponse = res.headers.get('content-type')?.includes('json')
          ? await res.json()
          : { ok: false, diagnostics: [{ level: 'error', message: `Compiler endpoint unavailable (HTTP ${res.status}). Run the Vite dev server.` }] };
        setState({ status: 'done', result, source: documentJson });
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setState({
            status: 'done',
            source: documentJson,
            result: { ok: false, diagnostics: [{ level: 'error', message: `Compile request failed: ${String(e)}` }] },
          });
        }
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [documentJson]);

  if (state.status !== 'done') return <p className="empty">Compiling…</p>;
  const { result } = state;
  const stale = state.source !== documentJson;

  return (
    <div className={`asm-panel ${stale ? 'stale' : ''}`}>
      {result.diagnostics.length > 0 && (
        <ul className="diagnostics">
          {result.diagnostics.map((d, i) => (
            <li
              key={i}
              className={`diag diag-${d.level} ${d.node ? 'clickable' : ''}`}
              onClick={() => d.node && onFocusNode(d.node)}
            >
              <span className="diag-level">{d.level}</span>
              {d.message}
            </li>
          ))}
        </ul>
      )}
      {result.ok && (
        <>
          <dl className="asm-summary">
            <dt>Program</dt>
            <dd>
              {result.manifest.programWords} / {PROGRAM_WORDS} words
            </dd>
            <dt>Resolution</dt>
            <dd>
              {result.manifest.resolution} ({result.manifest.barMinutes} min per tick)
            </dd>
            <dt>Warm-up</dt>
            <dd>
              {result.manifest.warmupTicks} ticks (needs {result.manifest.historyTicks} of history)
            </dd>
            <dt>Stocks</dt>
            <dd>
              {result.manifest.buffers
                .filter((b) => b.used)
                .map((b) => `BUF${b.buf}=${b.symbol} (10^-${b.priceExponent})`)
                .join(', ') || 'none'}
            </dd>
            <dt>Variables</dt>
            <dd>
              {[...result.manifest.variableSlots.user, ...Object.values(result.manifest.variableSlots.loopCounters).map((v) => `${v} (loop)`)].join(', ') || 'none'}
            </dd>
          </dl>
          <div className="json-actions">
            <button type="button" onClick={() => download(result.asm, `${slug}.asm`)}>
              .asm
            </button>
            <button type="button" onClick={() => download(result.hex, `${slug}.hex`)}>
              .hex
            </button>
            <button
              type="button"
              onClick={() => download(JSON.stringify(result.manifest, null, 2), `${slug}.manifest.json`, 'application/json')}
            >
              manifest
            </button>
          </div>
          <pre className="asm-listing">{result.asm}</pre>
        </>
      )}
    </div>
  );
}
