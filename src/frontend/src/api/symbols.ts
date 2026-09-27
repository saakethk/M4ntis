import { list, record, requestJson, str } from './http.ts'

export type TickerHit = {
  symbol: string
  name: string
}

export async function searchTickers(query: string, limit = 6): Promise<TickerHit[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  const body = record(await requestJson(`/symbols?${params}`), 'Symbol search')
  return list(body.symbols, 'Symbol search').map((item) => {
    const row = record(item, 'Symbol search')
    const symbol = str(row, 'symbol', 'Symbol search')
    return { symbol, name: typeof row.name === 'string' ? row.name : symbol }
  })
}
