import { useEffect, useRef, useState, type FormEvent } from 'react'
import { askAssistant, listAssistantModels, type AgentStep, type ChatTurn, type ModelChoice } from '../../api/assistant.ts'
import { SparkleIcon } from '../../components/icons.tsx'
import type { AssistantGraph } from '../../flow/assistantGraph.ts'
import { choiceId, initialChoice, rememberChoice } from './modelChoice.ts'

type Message = ChatTurn & {
  steps?: AgentStep[]
  graph?: AssistantGraph | null
  applied?: boolean
}

type Props = {
  /** The canvas right now, sent with every request. */
  canvas: AssistantGraph
  canEdit: boolean
  onApply: (graph: AssistantGraph) => void
}

const HISTORY_TURNS = 6
const SUGGESTIONS = [
  'Build an SMA crossover on MSFT',
  'Buy NVDA when its z-score drops below -2',
  'Why does my strategy never trade?',
]

export function AssistantPanel({ canvas, canEdit, onApply }: Props) {
  const [models, setModels] = useState<ModelChoice[]>([])
  const [choice, setChoice] = useState<ModelChoice | null>(null)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [thread, setThread] = useState<Message[]>([])
  const [prompt, setPrompt] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let ignore = false
    listAssistantModels()
      .then((list) => {
        if (ignore) return
        setModels(list.models)
        setChoice(initialChoice(list.models, list.defaultChoice))
      })
      .catch((caught: unknown) => !ignore && setModelsError(caught instanceof Error ? caught.message : 'Could not load models.'))
    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => endRef.current?.scrollIntoView({ block: 'end' }), [thread, pending])

  const noUsableModel = models.length > 0 && !models.some((m) => m.available)

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || pending) return
    const history = thread.slice(-HISTORY_TURNS).map(({ role, content }) => ({ role, content }))
    setThread((current) => [...current, { role: 'user', content: trimmed }])
    setPrompt('')
    setPending(true)
    setError(null)
    try {
      const answer = await askAssistant({ prompt: trimmed, graph: canvas, history, choice })
      setThread((current) => [...current, { role: 'assistant', content: answer.reply, steps: answer.steps, graph: answer.graph }])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not reach the server.')
    } finally {
      setPending(false)
    }
  }

  function apply(index: number) {
    const graph = thread[index]?.graph
    if (!graph) return
    onApply(graph)
    setThread((current) => current.map((m, i) => (i === index ? { ...m, applied: true } : m)))
  }

  return (
    <section className="rail-panel assistant" aria-label="AI assistant">
      <header className="rail-head">
        <h2>
          <SparkleIcon size={14} /> AI Assistant
        </h2>
        <p>Describe a strategy and the agent builds, wires, and checks the blocks for you.</p>
      </header>
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
          {models.length === 0 ? <option value="">{modelsError ? 'Unavailable' : 'Loading…'}</option> : null}
          {models.map((m) => (
            <option key={choiceId(m)} value={choiceId(m)} disabled={!m.available}>
              {m.label}
              {m.available ? '' : ' (no API key)'}
            </option>
          ))}
        </select>
      </label>
      {noUsableModel ? <p className="assistant-error">No model has an API key yet. Add GEMINI_API_KEY or META_API_KEY to the repo-root .env.</p> : null}
      {modelsError ? <p className="assistant-error">{modelsError}</p> : null}

      <div className="assistant-thread" aria-live="polite">
        {thread.length === 0 ? (
          <div className="assistant-suggestions">
            {SUGGESTIONS.map((text) => (
              <button key={text} type="button" onClick={() => void send(text)} disabled={pending || noUsableModel}>
                {text}
              </button>
            ))}
          </div>
        ) : null}
        {thread.map((message, index) => (
          <div key={index} className={`bubble bubble-${message.role}`}>
            <p>{message.content}</p>
            {message.steps && message.steps.length > 0 ? (
              <details className="agent-steps">
                <summary>
                  {message.steps.length} agent step{message.steps.length === 1 ? '' : 's'}
                </summary>
                <ol>
                  {message.steps.map((step, i) => (
                    <li key={i} className={step.ok ? '' : 'failed'}>
                      <code>{step.tool}</code> {step.detail}
                    </li>
                  ))}
                </ol>
              </details>
            ) : null}
            {message.graph ? (
              <button type="button" className="assistant-apply" onClick={() => apply(index)} disabled={!canEdit || message.applied}>
                {message.applied ? 'Applied' : `Apply ${message.graph.nodes.length} blocks to canvas`}
              </button>
            ) : null}
          </div>
        ))}
        {pending ? <p className="bubble bubble-assistant pending">Working on it…</p> : null}
        <div ref={endRef} />
      </div>

      {error ? <p className="assistant-error">{error}</p> : null}
      <form
        className="assistant-form"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          void send(prompt)
        }}
      >
        <textarea
          value={prompt}
          placeholder="Ask or describe a strategy…"
          aria-label="Message the assistant"
          rows={3}
          maxLength={2000}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void send(prompt)
            }
          }}
        />
        <div className="assistant-form-bar">
          {thread.length > 0 ? (
            <button type="button" className="text-btn" onClick={() => setThread([])} disabled={pending}>
              New chat
            </button>
          ) : (
            <span />
          )}
          <button type="submit" className="rail-action compact" disabled={pending || !prompt.trim() || noUsableModel}>
            {pending ? 'Asking…' : 'Send'}
          </button>
        </div>
      </form>
    </section>
  )
}
