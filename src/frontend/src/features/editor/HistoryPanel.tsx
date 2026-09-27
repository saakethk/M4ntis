import { useEffect, useState } from 'react'
import { listStrategyVersions, type StrategyVersion } from '../../api/strategies.ts'
import { dateTime } from '../../lib/format.ts'

type Props = {
  strategyId: number
  onRevert: (versionId: number) => Promise<void>
  onClose: () => void
}

/** Saved versions of the strategy, newest first, each restorable. */
export function HistoryPanel({ strategyId, onRevert, onClose }: Props) {
  const [versions, setVersions] = useState<StrategyVersion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reverting, setReverting] = useState<number | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let ignore = false
    listStrategyVersions(strategyId)
      .then((rows) => !ignore && setVersions(rows))
      .catch((caught: unknown) => !ignore && setError(caught instanceof Error ? caught.message : 'Could not load saved versions.'))
    return () => {
      ignore = true
    }
  }, [strategyId, reload])

  async function revert(versionId: number) {
    setReverting(versionId)
    setError(null)
    try {
      await onRevert(versionId)
      setReload((n) => n + 1)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not restore this version.')
    } finally {
      setReverting(null)
    }
  }

  return (
    <section className="version-history" aria-label="Saved versions">
      <div className="version-history-head">
        <h2>Saved versions</h2>
        <button type="button" className="quiet" onClick={onClose}>
          Close
        </button>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {versions == null && !error ? <p className="version-empty">Loading versions…</p> : null}
      {versions?.length === 0 ? <p className="version-empty">No saved versions yet.</p> : null}
      {versions && versions.length > 0 ? (
        <ul>
          {versions.map((version, index) => (
            <li key={version.id} className="version-row">
              <span className="version-name">
                {version.name}
                {index === 0 ? <em> · current</em> : null}
              </span>
              <time dateTime={version.createdAt}>{dateTime(version.createdAt)}</time>
              <button type="button" className="quiet" onClick={() => void revert(version.id)} disabled={reverting != null || index === 0}>
                {reverting === version.id ? 'Restoring…' : 'Restore'}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
