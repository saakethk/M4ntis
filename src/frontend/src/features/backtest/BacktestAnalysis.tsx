import { useEffect, useState, type FormEvent } from 'react'
import { analyzeBacktest } from '../../api/analysis.ts'
import { listAssistantModels, type ModelChoice } from '../../api/assistant.ts'
import { SparkleIcon } from '../../components/icons.tsx'
import { choiceId, initialChoice, rememberChoice } from '../assistant/modelChoice.ts'

type Result = { question: string; text: string; model: string }

/** Ask an AI model to explain a finished run and suggest changes, with optional follow-up questions. */
export function BacktestAnalysis({ backtestId }: { backtestId: number }) {
  const [models, setModels] = useState<ModelChoice[]>([])
  const [choice, setChoice] = useState<ModelChoice | null>(null)
  const [question, setQuestion] = useState('')
  const [results, setResults] = useState<Result[]>([])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    listAssistantModels()
      .then((list) => {
        if (ignore) return
        setModels(list.models)
        setChoice(initialChoice(list.models, list.defaultChoice))
      })
      .catch((caught: unknown) => !ignore && setError(caught instanceof Error ? caught.message : 'Could not load models.'))
    return () => {
      ignore = true
    }
  }, [])

  const noUsableModel = models.length > 0 && !models.some((m) => m.available)

  async function run(event?: FormEvent) {
    event?.preventDefault()
    if (pending) return
    const asked = question.trim()
    setPending(true)
    setError(null)
    try {
      const answer = await analyzeBacktest(backtestId, { choice, question: asked })
      setResults((current) => [...current, { question: asked, text: answer.analysis, model: answer.model }])
      setQuestion('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not analyze this backtest.')
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="plan-card analysis-card" aria-label="AI analysis">
      <header className="analysis-head">
        <h2>
          <SparkleIcon size={16} /> AI analysis
        </h2>
        <label className="assistant-model">
          Model
          <select
            value={choice ? choiceId(choice) : ''}
            disabled={pending || models.length === 0}
            onChange={(event) => {
              const next = models.find((m) => choiceId(m) === event.target.value)
              if (!next) return
              setChoice(next)
              rememberChoice(next)
            }}
          >
            {models.length === 0 ? <option value="">Loading…</option> : null}
            {models.map((m) => (
              <option key={choiceId(m)} value={choiceId(m)} disabled={!m.available}>
                {m.label}
                {m.available ? '' : ' (no API key)'}
              </option>
            ))}
          </select>
        </label>
      </header>
      {results.length === 0 ? (
        <p className="analysis-intro">Get an explanation of this run: why it traded the way it did, the risks in the result, and what to change next.</p>
      ) : null}
      {results.map((result, index) => (
        <div className="analysis-result" key={index}>
          {result.question ? <p className="analysis-question">{result.question}</p> : null}
          <p className="analysis-text">{result.text}</p>
          {result.model ? <p className="analysis-model">{result.model}</p> : null}
        </div>
      ))}
      {noUsableModel ? <p className="form-error">No model has an API key yet. Add GEMINI_API_KEY or META_API_KEY to the repo-root .env.</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
      <form className="analysis-form" onSubmit={run}>
        <input
          value={question}
          maxLength={1000}
          aria-label="Question about this backtest"
          placeholder={results.length === 0 ? 'Optional: ask something specific' : 'Ask a follow-up question'}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button type="submit" className="primary" disabled={pending || noUsableModel || (results.length > 0 && !question.trim())}>
          {pending ? 'Analyzing…' : results.length === 0 ? 'Analyze backtest' : 'Ask'}
        </button>
      </form>
    </section>
  )
}
