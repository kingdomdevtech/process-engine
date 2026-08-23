import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronRight, Wand2 } from 'lucide-react'
import { api } from '../api.js'
import DataPicker from './DataPicker.jsx'
import HtmlField from './HtmlField.jsx'
import ColorField from './fields/ColorField.jsx'
import KeyValueField from './fields/KeyValueField.jsx'
import SecretField from './fields/SecretField.jsx'
import TagListField from './fields/TagListField.jsx'
import Field from './ui/Field.jsx'
import { exampleField } from '../schemaExample.js'

/**
 * The step configuration form, generated from the plugin's config JSON Schema.
 *
 * Nothing here knows about any particular plugin: the widget comes from the
 * schema type, and a plugin refines the result by declaring `x-ui` hints (see
 * `process_engine.ui`) — a group, an "advanced" flag, a widget override, human
 * wording for enum values, or a condition for when the field is worth showing
 * at all. A plugin that declares none of it still renders sensibly.
 */

const LIST_WIDGETS = new Set(['tags', 'emails', 'files'])

const hintsOf = (spec) => spec['x-ui'] ?? {}

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)

function firstType(spec) {
  const type = spec.type
  return Array.isArray(type) ? type.find((entry) => entry !== 'null') : type
}

/** Items a chip can hold: scalars, and the untyped items of `list[Any]`. */
function itemsAreScalar(spec) {
  const items = spec.items
  if (!items) return true
  if (items.$ref || items.properties) return false
  return !items.type || ['string', 'number', 'integer', 'boolean'].includes(items.type)
}

/**
 * Which control to draw. A value assigned with ƒx replaces a list or object
 * with an expression string, so the structured widgets step aside for the raw
 * editor rather than showing nothing when that happens.
 */
function resolveWidget(spec, value) {
  const declared = hintsOf(spec).widget
  if (spec.enum) return 'select'
  if (spec.format === 'html' || declared === 'html') return 'html'
  if (declared === 'json') return 'json'

  const type = firstType(spec)
  if (LIST_WIDGETS.has(declared) || (!declared && type === 'array' && itemsAreScalar(spec))) {
    return Array.isArray(value) || value === undefined ? declared ?? 'tags' : 'json'
  }
  if (declared === 'keyvalue' || (!declared && type === 'object' && spec.additionalProperties)) {
    return isPlainObject(value) || value === undefined ? 'keyvalue' : 'json'
  }
  if (declared) return declared // password, color, sql, textarea, path, email
  if (type === 'boolean') return 'boolean'
  if (type === 'integer' || type === 'number') return 'number'
  if (type === 'string') return 'text'
  if (type === 'array' || type === 'object') return 'json'
  return 'value' // an untyped field (Any) — a scalar or an expression
}

/** `not_equals` → `Not equals`, leaving `GET` and `us-east-1` alone. */
function humanizeOption(value) {
  return /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/.test(value)
    ? value.replace(/_/g, ' ').replace(/^./, (first) => first.toUpperCase())
    : value
}

/** An example the plugin declared itself — used as a field's placeholder. */
function placeholderFor(spec) {
  const hints = hintsOf(spec)
  if (hints.placeholder) return hints.placeholder
  const declared = Array.isArray(spec.examples) && spec.examples.length > 0 ? spec.examples[0] : spec.example
  const example = Array.isArray(declared) ? declared[0] : declared // one chip's worth, for a list
  if (example === undefined || example === null || isPlainObject(example)) return ''
  return String(example)
}

/**
 * The expression addressing the first value of `kind` in what the steps above
 * this one produce — how a field with an `x-ui.detect` hint gets filled.
 *
 * The picker's groups arrive trigger-first, then every ancestor in definition
 * order, so the search runs backwards: the step nearest this one wins. Before
 * the process has ever run there is no recorded output to look inside, and the
 * nearest step's whole output is the closest true answer — `for_each` digs the
 * list out of it at run time.
 */
function detectPath(groups, kind) {
  const upstream = (groups ?? []).filter((group) => group.key !== 'trigger')
  for (let index = upstream.length - 1; index >= 0; index -= 1) {
    const match = (upstream[index].fields ?? []).find((field) => field.type === kind)
    if (match) return match.path
  }
  return upstream[upstream.length - 1]?.fields?.[0]?.path ?? null
}

/**
 * "Which list is this?" answered by the graph instead of typed.
 *
 * It fills an empty field on its own the first time the panel opens — the
 * detection is the field's documented default, so making someone press a
 * button to get it would be asking them to confirm what they already asked
 * for — and stays available afterwards for a field that needs re-pointing
 * once the connection above it changes.
 */
function DetectAction({ kind, processId, stepId, isEmpty, onDetect }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const attempted = useRef(false)
  const apply = useRef(onDetect)
  apply.current = onDetect

  const detect = useCallback(async () => {
    if (!processId) return
    setBusy(true)
    try {
      const { groups } = await api.get(`/api/processes/${processId}/steps/${stepId}/picker`)
      const path = detectPath(groups, kind)
      if (path) {
        setNote('')
        apply.current(path)
      } else {
        setNote('Nothing above this step to take a list from.')
      }
    } catch (error) {
      /* Detection reads the saved graph, so a step added since the last save is
         not there to look above yet. */
      setNote(error.status === 404 ? 'Save the process, then detect what the step above delivers.' : String(error.message))
    } finally {
      setBusy(false)
    }
  }, [processId, stepId, kind])

  useEffect(() => {
    if (attempted.current || !isEmpty || !processId) return
    attempted.current = true
    detect()
  }, [isEmpty, processId, detect])

  return (
    <button
      type="button"
      className="flex items-center gap-1 rounded border border-line bg-surface px-1.5 py-px text-[10px] font-semibold text-brand-text transition-colors hover:border-brand hover:bg-brand-soft disabled:opacity-50"
      title={
        processId
          ? note || 'Read the connected step above and fill this in'
          : 'Save the process first — detection reads the step above this one'
      }
      aria-label="Detect from the previous step"
      disabled={busy || !processId}
      onClick={detect}
    >
      <Wand2 size={11} aria-hidden="true" />
      {busy ? 'Detecting…' : 'Detect'}
    </button>
  )
}

/** A field is shown while the field its `showIf` names holds one of the listed values. */
function isVisible(spec, config, properties) {
  const rule = hintsOf(spec).showIf
  if (!rule) return true
  const target = properties[rule.field] ?? {}
  const current = config[rule.field] ?? target.default
  return (rule.in ?? []).includes(current)
}

function JsonField({ value, onCommit, strict, example, id, describedBy }) {
  const [text, setText] = useState(value === undefined ? '' : JSON.stringify(value, null, 2))
  const [invalid, setInvalid] = useState(false)

  const commit = () => {
    const trimmed = text.trim()
    if (!trimmed) {
      setInvalid(false)
      onCommit(undefined)
      return
    }
    try {
      onCommit(JSON.parse(trimmed))
      setInvalid(false)
    } catch {
      if (strict) {
        setInvalid(true)
      } else {
        onCommit(text) // untyped fields accept raw text (e.g. expressions)
        setInvalid(false)
      }
    }
  }

  const fallback = strict ? 'JSON, e.g. {"key": "value"}' : 'value or expression, e.g. {{ steps.x.output.y }}'
  return (
    <>
      <textarea
        id={id}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        className={`textarea min-h-14 ${invalid ? 'input-invalid' : ''}`}
        value={text}
        spellCheck={false}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        placeholder={example === undefined ? fallback : `e.g. ${JSON.stringify(example)}`}
      />
      {invalid && (
        <p className="error-text mt-1" role="alert">
          Not valid JSON — the previous value is still in effect.
        </p>
      )}
    </>
  )
}

/**
 * One line holding whatever the field accepts — a number, a word, an
 * expression. Typed text is parsed, so `250` stays a number and a date stays
 * a string, which is what the comparison in a Condition step needs.
 */
function ValueField({ value, onCommit, placeholder, id, describedBy }) {
  const asText = value === undefined || value === null ? '' : String(value)
  const [text, setText] = useState(asText)

  /* Typing only moves `text` — the value is committed on blur — so this fires
     for a change that came from outside the form (ƒx, Detect) and would
     otherwise fill the config without the field ever showing it. */
  useEffect(() => setText(asText), [asText])

  const commit = () => {
    const trimmed = text.trim()
    if (!trimmed) return onCommit(undefined)
    try {
      onCommit(JSON.parse(trimmed))
    } catch {
      onCommit(text)
    }
  }

  return (
    <input
      id={id}
      aria-describedby={describedBy}
      className="input"
      type="text"
      value={text}
      placeholder={placeholder || 'A value, or ƒx to take one from an earlier step'}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
    />
  )
}

function NumberField({ spec, hints, value, onCommit, id, describedBy }) {
  // an expression resolves to a number at run time, so keep text input in that case
  if (typeof value === 'string') {
    return (
      <input
        id={id}
        aria-describedby={describedBy}
        className="input font-mono text-xs"
        type="text"
        value={value}
        onChange={(event) => onCommit(event.target.value || undefined)}
      />
    )
  }
  const input = (
    <input
      id={id}
      aria-describedby={describedBy}
      className="input"
      type="number"
      min={spec.minimum ?? spec.exclusiveMinimum}
      max={spec.maximum}
      value={value ?? ''}
      placeholder={placeholderFor(spec) || String(spec.default ?? '')}
      onChange={(event) => onCommit(event.target.value === '' ? undefined : Number(event.target.value))}
    />
  )
  if (!hints.unit) return input
  return (
    <div className="flex items-center gap-2">
      {input}
      <span className="shrink-0 text-[12px] text-fg-muted">{hints.unit}</span>
    </div>
  )
}

function FieldInput({ name, spec, value, onCommit, processes, root, pickExpression, id, describedBy }) {
  const common = { id, 'aria-describedby': describedBy }
  const hints = hintsOf(spec)
  const placeholder = placeholderFor(spec)

  if (name === 'process_id' && processes?.length) {
    return (
      <select {...common} className="select" value={value ?? ''} onChange={(event) => onCommit(event.target.value || undefined)}>
        <option value="">— choose a process —</option>
        {processes.map((process) => (
          <option key={process.id} value={process.id}>
            {process.name}
          </option>
        ))}
      </select>
    )
  }

  switch (resolveWidget(spec, value)) {
    case 'select':
      return (
        <select
          {...common}
          className="select"
          value={value ?? spec.default ?? ''}
          onChange={(event) => onCommit(event.target.value)}
        >
          {spec.enum.map((option) => (
            <option key={option} value={option}>
              {hints.labels?.[option] ?? humanizeOption(String(option))}
            </option>
          ))}
        </select>
      )

    case 'boolean': {
      const checked = value ?? spec.default ?? false
      return (
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg-muted">
          <input
            {...common}
            type="checkbox"
            className="checkbox"
            checked={checked}
            onChange={(event) => onCommit(event.target.checked)}
          />
          {checked ? 'Yes' : 'No'}
        </label>
      )
    }

    case 'number':
      return <NumberField spec={spec} hints={hints} value={value} onCommit={onCommit} {...common} />

    case 'html':
      return <HtmlField value={value} onCommit={onCommit} id={id} />

    case 'password':
      return <SecretField value={value} onCommit={onCommit} placeholder={placeholder} {...common} />

    case 'color':
      return <ColorField value={value} onCommit={onCommit} spec={spec} {...common} />

    case 'tags':
    case 'emails':
    case 'files':
      return (
        <TagListField
          value={value}
          onCommit={onCommit}
          hints={{ ...hints, widget: resolveWidget(spec, value) }}
          placeholder={placeholder}
          {...common}
        />
      )

    case 'keyvalue':
      return (
        <KeyValueField
          value={value}
          onCommit={onCommit}
          spec={spec}
          hints={hints}
          pickExpression={pickExpression}
          {...common}
        />
      )

    case 'sql':
    case 'textarea':
      return (
        <textarea
          {...common}
          className={`textarea min-h-20 ${resolveWidget(spec, value) === 'textarea' ? 'font-sans text-[13px]' : ''}`}
          value={value ?? ''}
          spellCheck={false}
          placeholder={placeholder}
          onChange={(event) => onCommit(event.target.value === '' ? undefined : event.target.value)}
        />
      )

    case 'email':
    case 'path':
    case 'text':
      return (
        <input
          {...common}
          className="input"
          type={resolveWidget(spec, value) === 'email' ? 'email' : 'text'}
          value={value ?? ''}
          placeholder={placeholder || String(spec.default ?? '')}
          onChange={(event) => onCommit(event.target.value === '' ? undefined : event.target.value)}
        />
      )

    case 'value':
      return <ValueField value={value} onCommit={onCommit} placeholder={placeholder} {...common} />

    default:
      return (
        <JsonField
          {...common}
          value={value}
          onCommit={onCommit}
          strict={firstType(spec) === 'array' || firstType(spec) === 'object'}
          example={exampleField(spec, root)}
        />
      )
  }
}

/**
 * Fields that can hold an expression. Booleans and closed enums cannot, and a
 * key/value editor carries ƒx on each row instead — assigning to the field as
 * a whole would swap the object for a string.
 */
function isAssignable(spec, value) {
  if (spec.enum || firstType(spec) === 'boolean') return false
  return resolveWidget(spec, value) !== 'keyvalue'
}

/** Group the properties as declared, splitting the advanced ones out of each. */
function toSections(properties) {
  const sections = []
  const byTitle = new Map()
  for (const [name, spec] of Object.entries(properties)) {
    const hints = hintsOf(spec)
    const title = hints.group ?? ''
    if (!byTitle.has(title)) {
      const section = { title, basic: [], advanced: [] }
      byTitle.set(title, section)
      sections.push(section)
    }
    byTitle.get(title)[hints.advanced ? 'advanced' : 'basic'].push({ name, spec })
  }
  return sections
}

export default function SchemaForm({ nodeId, schema, config, onChange, processes, processId }) {
  const [picking, setPicking] = useState(null)
  const properties = schema?.properties ?? {}
  const required = new Set(schema?.required ?? [])
  const sections = toSections(properties)
  const titled = sections.filter((section) => section.title).length > 1

  const assign = (field, picked) => {
    const expression = typeof picked === 'string' ? picked : picked?.path ?? picked
    const sourceType = typeof picked === 'object' ? picked?.type : undefined
    const current = config[field]
    const spec = properties[field] ?? {}

    if (sourceType === 'array') {
      onChange(field, expression)
      return
    }

    if (firstType(spec) === 'array') {
      onChange(field, Array.isArray(current) ? [...current, expression] : expression)
      return
    }

    if (typeof current === 'string' && current.trim()) {
      onChange(field, `${current}${expression}`) // append into the existing template
      return
    }

    onChange(field, expression)
  }

  const pickExpression = (label, apply) => setPicking({ label, apply })

  const renderField = ({ name, spec }) => {
    const value = config[name]
    const detect = hintsOf(spec).detect
    const assignable = isAssignable(spec, value)
    return (
      <Field
        key={`${nodeId}:${name}`}
        label={spec.title || name}
        required={required.has(name)}
        description={spec.description}
        action={
          (detect || assignable) && (
          <span className="flex items-center gap-1">
            {detect && (
              <DetectAction
                kind={detect}
                processId={processId}
                stepId={nodeId}
                isEmpty={value === undefined || value === null || value === ''}
                onDetect={(expression) => onChange(name, expression)}
              />
            )}
            {assignable && (
              <button
                type="button"
                className="rounded border border-line bg-surface px-1.5 py-px text-[10px] font-semibold text-brand-text transition-colors hover:border-brand hover:bg-brand-soft"
                title="Insert a value from an earlier step"
                aria-label={`Insert a value from an earlier step into ${spec.title || name}`}
                onClick={() => pickExpression(spec.title || name, (expression) => assign(name, expression))}
              >
                ƒx
              </button>
            )}
          </span>
          )
        }
      >
        {({ id, 'aria-describedby': describedBy }) => (
          <FieldInput
            id={id}
            describedBy={describedBy}
            name={name}
            spec={spec}
            value={value}
            onCommit={(next) => onChange(name, next)}
            processes={processes}
            root={schema}
            pickExpression={pickExpression}
          />
        )}
      </Field>
    )
  }

  return (
    <div>
      {sections.map((section, index) => {
        const basic = section.basic.filter(({ spec }) => isVisible(spec, config, properties))
        const advanced = section.advanced.filter(({ spec }) => isVisible(spec, config, properties))
        if (basic.length === 0 && advanced.length === 0) return null

        return (
          <section key={section.title || index} className={index > 0 ? 'mt-4' : ''}>
            {titled && section.title && <h4 className="section-label mb-2">{section.title}</h4>}
            {basic.map(renderField)}

            {advanced.length > 0 && (
              <details className="group mb-3 rounded-md border border-line bg-surface-2 px-2.5 py-2 last:mb-0">
                <summary className="flex cursor-pointer list-none items-center gap-1 text-[11px] font-semibold text-fg-muted hover:text-fg">
                  <ChevronRight
                    size={12}
                    className="transition-transform group-open:rotate-90"
                    aria-hidden="true"
                  />
                  Advanced
                  <span className="font-normal text-fg-subtle">({advanced.length})</span>
                </summary>
                <div className="mt-2.5">{advanced.map(renderField)}</div>
              </details>
            )}
          </section>
        )
      })}

      {Object.keys(properties).length === 0 && <p className="muted">This plugin needs no configuration.</p>}

      {picking && (
        <DataPicker
          processId={processId}
          stepId={nodeId}
          fieldName={picking.label}
          onPick={picking.apply}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  )
}
