import react from '@vitejs/plugin-react'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'

const COMPILER_DIR = fileURLToPath(new URL('../../compiler', import.meta.url))
const PYTHON = process.env.TRADECPU_PYTHON ?? 'python3'

/** Dev-only `POST /api/compile`: pipes the strategy document into `python -m tradecpu compile - --json`. */
function tradecpuCompiler(): Plugin {
  return {
    name: 'tradecpu-compiler',
    configureServer(server) {
      server.middlewares.use('/api/compile', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end()
          return
        }
        const reply = (status: number, body: unknown) => {
          res.statusCode = status
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(body))
        }
        const url = new URL(req.url ?? '', 'http://localhost')
        const priceExps = url.searchParams.getAll('priceExp').flatMap((p) => ['--price-exp', p])
        const child = spawn(PYTHON, ['-m', 'tradecpu', 'compile', '-', '--json', ...priceExps], {
          cwd: COMPILER_DIR,
        })
        let stdout = ''
        let stderr = ''
        child.stdout.on('data', (d) => (stdout += d))
        child.stderr.on('data', (d) => (stderr += d))
        child.on('error', (e) =>
          reply(500, { ok: false, diagnostics: [{ level: 'error', message: `Could not run ${PYTHON}: ${e.message}` }] }),
        )
        child.on('close', () => {
          try {
            reply(200, JSON.parse(stdout))
          } catch {
            reply(500, { ok: false, diagnostics: [{ level: 'error', message: stderr.trim() || 'Compiler crashed' }] })
          }
        })
        req.pipe(child.stdin)
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tradecpuCompiler()],
})
