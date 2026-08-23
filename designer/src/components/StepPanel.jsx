import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Braces, FormInput, Lightbulb } from 'lucide-react'
import SchemaForm from './SchemaForm.jsx'
import { exampleConfig } from '../schemaExample.js'

export default function StepPanel({
  node,
  plugin,
  processes,
  processId,
  issues,
  onRename,
  onConfigField,
  onConfigJson,
}) {
  const [mode, setMode] = useState('form')
  const [jsonText, setJsonText] = useState('')
  const [jsonError, setJsonError] = useState('')
  const [showExample, setShowExample] = useState(false)

  // a pre-configured config for this plugin, derived from its schema
  const example = useMemo(
    () => JSON.stringify(exampleConfig(plugin?.config_schema), null, 2),
    [plugin?.config_schema],
  )
  const hasExample = Object.keys(plugin?.config_schema?.properties ?? {}).length > 0

  useEffect(() => {
    setJsonText(JSON.stringify(node.data.config ?? {}, null, 2))
    setJsonError('')
    setShowExample(false)
  }, [node.id, mode])

  const applyJson = () => {
    try {
      const parsed = jsonText.trim() ? JSON.parse(jsonText) : {}
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('config must be a JSON object')
      }
      onConfigJson(node.id, parsed)
      setJsonError('')
    } catch (error) {
      setJsonError(String(error.message || error))
    }
  }

  return (
    <div className="panel">
      <label className="label mb-1.5" htmlFor="pe-step-name">
        Step name
      </label>
      <input
        id="pe-step-name"
        className="input"
        value={node.data.label}
        onChange={(event) => onRename(node.id, event.target.value)}
      />
      <p className="hint mt-1">
        Also how other steps address it: <code className="code">{`{{ steps.${(node.data.label || '').trim() || 'step_name'}.output }}`}</code>
      </p>

      {issues.length > 0 && (
        <div className="mt-3 rounded-md border border-bad-fg/30 bg-bad-bg px-2.5 py-2">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold text-bad-fg">
            <AlertTriangle size={12} aria-hidden="true" />
            {issues.length} {issues.length === 1 ? 'issue' : 'issues'}
          </p>
          <ul className="mt-1 list-inside list-disc text-[11px] text-bad-fg">
            {issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="tab-list mt-3 w-full" role="tablist" aria-label="Configuration editor">
        <button
          role="tab"
          aria-selected={mode === 'form'}
          className={`tab flex flex-1 items-center justify-center gap-1.5 ${mode === 'form' ? 'is-active' : ''}`}
          onClick={() => setMode('form')}
        >
          <FormInput size={13} />
          Form
        </button>
        <button
          role="tab"
          aria-selected={mode === 'json'}
          className={`tab flex flex-1 items-center justify-center gap-1.5 ${mode === 'json' ? 'is-active' : ''}`}
          onClick={() => setMode('json')}
        >
          <Braces size={13} />
          JSON
        </button>
      </div>

      <div className="mt-3">
        {mode === 'form' ? (
          <SchemaForm
            nodeId={node.id}
            schema={plugin?.config_schema}
            config={node.data.config ?? {}}
            onChange={(field, value) => onConfigField(node.id, field, value)}
            processes={processes}
            processId={processId}
          />
        ) : (
          <>
            <textarea
              className={`textarea min-h-56 ${jsonError ? 'input-invalid' : ''}`}
              value={jsonText}
              spellCheck={false}
              aria-label="Step configuration as JSON"
              aria-invalid={Boolean(jsonError)}
              onChange={(event) => setJsonText(event.target.value)}
            />
            {jsonError && (
              <p className="error-text mt-1" role="alert">
                {jsonError}
              </p>
            )}
            <div className="mt-2 flex items-center gap-1.5">
              <button className="btn btn-sm btn-primary" onClick={applyJson}>
                Apply JSON
              </button>
              {hasExample && (
                <button className="btn btn-sm btn-ghost" onClick={() => setShowExample((shown) => !shown)}>
                  <Lightbulb size={13} />
                  {showExample ? 'Hide example' : 'Show example'}
                </button>
              )}
            </div>

            {showExample && (
              <div className="mt-2.5 rounded-md border border-line bg-surface-2 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold text-fg-muted">
                    Example — {plugin?.name ?? node.data.plugin}
                  </span>
                  <button
                    className="link text-[11px]"
                    onClick={() => {
                      setJsonText(example)
                      setJsonError('')
                    }}
                  >
                    Use this
                  </button>
                </div>
                <pre className="mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-fg-muted">
                  {example}
                </pre>
                <p className="hint mt-1">
                  Loads into the editor only — nothing changes on the step until you press Apply JSON.
                </p>
              </div>
            )}
          </>
        )}
      </div>

      <div className="mt-4 rounded-md border border-line bg-surface-2 p-2.5">
        <p className="hint">
          Press <strong className="font-semibold text-fg">ƒx</strong> beside a field to pull a value from an earlier
          step, or type an expression directly:
        </p>
        <ul className="mt-1.5 space-y-0.5">
          {['{{ trigger.x }}', '{{ steps.<name>.output.y }}', '{{ secrets.<name> }}'].map((snippet) => (
            <li key={snippet}>
              <code className="code text-[10px]">{snippet}</code>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
