import { useId } from 'react'

/**
 * One form row: label, optional required marker, control, help text, error.
 *
 * The label is always bound to the control and the description/error are wired
 * through aria-describedby, so screen readers announce the same context a
 * sighted user gets from the layout.
 */
export default function Field({ label, required, description, error, action, children, htmlFor }) {
  const generated = useId()
  const id = htmlFor ?? generated
  const describedBy = [description && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ')

  return (
    <div className="mb-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <label className="label min-w-0" htmlFor={id}>
          <span className="truncate">{label}</span>
          {required && (
            <span className="text-bad-fg" title="Required">
              *
            </span>
          )}
        </label>
        {action && <span className="ml-auto shrink-0">{action}</span>}
      </div>

      {typeof children === 'function'
        ? children({ id, 'aria-describedby': describedBy || undefined, 'aria-invalid': error ? true : undefined })
        : children}

      {description && (
        <p id={`${id}-hint`} className="hint mt-1">
          {description}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="error-text mt-1" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
