import { useState } from 'react'
import { Eye, EyeOff, KeyRound, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { secretExpression, secretReference, useSecretNames } from '../../secrets.js'

/**
 * A password input that steers towards the secrets store.
 *
 * Typing a password straight into a step writes it into the process
 * definition, which is then exported, versioned and visible to every editor.
 * The stored secrets are encrypted at rest and resolved only as the step runs,
 * so this field offers them by name — picking one writes the
 * `{{ secrets.… }}` expression that used to have to be typed from memory.
 */
export default function SecretField({ value, onCommit, placeholder, id, describedBy }) {
  const [revealed, setRevealed] = useState(false)
  const names = useSecretNames()
  const reference = secretReference(value)

  if (reference) {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2.5 py-1.5">
        <KeyRound size={13} className="shrink-0 text-brand-text" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg">
          Stored secret <strong className="font-semibold">{reference}</strong>
        </span>
        <button
          type="button"
          className="grid size-5 shrink-0 place-items-center rounded text-fg-subtle transition-colors hover:bg-bad-bg hover:text-bad-fg"
          aria-label={`Stop using the secret ${reference}`}
          title="Use a different value"
          onClick={() => onCommit(undefined)}
        >
          <X size={12} />
        </button>
      </div>
    )
  }

  return (
    <div>
      <div className="flex gap-1.5">
        <div className="relative flex-1">
          <input
            id={id}
            aria-describedby={describedBy}
            className="input pr-8"
            type={revealed ? 'text' : 'password'}
            autoComplete="off"
            value={value ?? ''}
            placeholder={placeholder}
            onChange={(event) => onCommit(event.target.value === '' ? undefined : event.target.value)}
          />
          <button
            type="button"
            className="absolute right-1 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-fg-subtle transition-colors hover:text-fg"
            aria-label={revealed ? 'Hide the value' : 'Show the value'}
            title={revealed ? 'Hide' : 'Show'}
            onClick={() => setRevealed((shown) => !shown)}
          >
            {revealed ? <EyeOff size={13} /> : <Eye size={13} />}
          </button>
        </div>

        {names.length > 0 && (
          <select
            className="select w-auto shrink-0 text-xs"
            aria-label="Use a stored secret"
            value=""
            onChange={(event) => event.target.value && onCommit(secretExpression(event.target.value))}
          >
            <option value="">Use a secret…</option>
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        )}
      </div>

      {value && !revealed && (
        <p className="hint mt-1">
          Typed here, this is saved inside the process.{' '}
          <Link className="link" to="/app/secrets">
            Store it as a secret
          </Link>{' '}
          to keep it out.
        </p>
      )}
    </div>
  )
}
