import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { loadEnv } from 'vite'
import { API_PREFIXES, apiProxy, backendProxyTarget, readListenPort } from './devProxy.ts'
import { resolveApiBase } from './src/apiBase.ts'

const repoRoot = fileURLToPath(new URL('../..', import.meta.url))

describe('resolveApiBase', () => {
  it('stays on the page origin while Vite is serving the app', () => {
    assert.equal(
      resolveApiBase('http://localhost:8001', { dev: true, pageHostname: '0.0.0.0' }),
      '',
    )
    assert.equal(resolveApiBase('https://api.example.com', { dev: true, pageHostname: 'localhost' }), '')
    assert.equal(resolveApiBase(undefined, { dev: true }), '')
  })

  it('points a local API at the same host the page was opened on', () => {
    assert.equal(
      resolveApiBase('http://localhost:8001', { pageHostname: '0.0.0.0' }),
      'http://0.0.0.0:8001',
    )
    assert.equal(
      resolveApiBase('http://localhost:8001/', { pageHostname: '127.0.0.1' }),
      'http://127.0.0.1:8001',
    )
    assert.equal(
      resolveApiBase('http://0.0.0.0:8001', { pageHostname: 'localhost' }),
      'http://localhost:8001',
    )
    assert.equal(
      resolveApiBase('http://localhost:8001', { pageHostname: 'localhost' }),
      'http://localhost:8001',
    )
  })

  it('keeps an explicit non-local API host', () => {
    assert.equal(
      resolveApiBase('https://api.example.com/v1/', { pageHostname: '0.0.0.0' }),
      'https://api.example.com/v1',
    )
  })

  it('defaults an empty production URL to localhost, then the page host', () => {
    assert.equal(resolveApiBase('  ', { pageHostname: '127.0.0.1' }), 'http://127.0.0.1:8001')
    assert.equal(resolveApiBase(undefined), 'http://localhost:8001')
    assert.equal(resolveApiBase('http://0.0.0.0:9000'), 'http://localhost:9000')
  })
})

describe('dev server proxy', () => {
  it('forwards API prefixes to the backend port', () => {
    assert.equal(backendProxyTarget({}), 'http://127.0.0.1:8001')
    assert.equal(backendProxyTarget({ BACKEND_PORT: '9001' }), 'http://127.0.0.1:9001')
    assert.equal(backendProxyTarget({ VITE_API_URL: 'http://localhost:8001' }), 'http://127.0.0.1:8001')
    assert.equal(backendProxyTarget({ VITE_API_URL: 'http://0.0.0.0:8001/' }), 'http://127.0.0.1:8001')
    assert.equal(backendProxyTarget({ VITE_API_URL: 'https://api.example.com' }), 'https://api.example.com')
    assert.throws(() => readListenPort('nope', 8001, 'BACKEND_PORT'), /BACKEND_PORT/)

    const proxy = apiProxy('http://127.0.0.1:8001')
    assert.deepEqual(Object.keys(proxy), [...API_PREFIXES])
    for (const prefix of API_PREFIXES) {
      assert.equal(proxy[prefix].target, 'http://127.0.0.1:8001')
      assert.equal(proxy[prefix].changeOrigin, true)
    }
  })

  it('wires that proxy into the Vite dev and preview servers', async () => {
    const env = loadEnv('test', repoRoot, '')
    const expectedTarget = backendProxyTarget(env)
    const loaded = (await import('./vite.config.ts')).default
    const config = await Promise.resolve(
      typeof loaded === 'function' ? loaded({ command: 'serve', mode: 'test' }) : loaded,
    )
    const serverProxy = config.server?.proxy
    const previewProxy = config.preview?.proxy
    assert.ok(serverProxy)
    assert.ok(previewProxy)
    for (const prefix of API_PREFIXES) {
      assert.equal(serverProxy[prefix].target, expectedTarget)
      assert.equal(serverProxy[prefix].changeOrigin, true)
      assert.equal(previewProxy[prefix].target, expectedTarget)
    }
    assert.equal(config.server?.port, readListenPort(env.FRONTEND_PORT, 8002, 'FRONTEND_PORT'))
    assert.notEqual(new URL(expectedTarget).hostname, '0.0.0.0')
  })
})
