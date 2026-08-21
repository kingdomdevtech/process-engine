/**
 * A colour swatch beside the value, so a colour can be chosen by looking at it
 * rather than by knowing what `#1f2937` means.
 *
 * The text input stays: it accepts named colours and `{{ expressions }}`, which
 * the native picker cannot represent.
 */
const HEX = /^#[0-9a-f]{6}$/i

export default function ColorField({ value, onCommit, spec = {}, id, describedBy }) {
  const current = value ?? spec.default ?? ''
  const swatch = HEX.test(current) ? current : '#000000'

  return (
    <div className="flex gap-1.5">
      <input
        type="color"
        className="size-8 shrink-0 cursor-pointer rounded-md border border-line bg-surface p-0.5"
        aria-label="Choose a colour"
        value={swatch}
        onChange={(event) => onCommit(event.target.value)}
      />
      <input
        id={id}
        aria-describedby={describedBy}
        className="input font-mono text-xs"
        type="text"
        value={current}
        placeholder={spec.default ?? '#1f2937'}
        onChange={(event) => onCommit(event.target.value === '' ? undefined : event.target.value)}
      />
    </div>
  )
}
