import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from '../theme.js'

export const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

/**
 * Segmented theme control. Three explicit choices rather than a two-state
 * switch, because "follow my OS" is a distinct preference from either fixed
 * theme — a switch cannot represent it, and silently dropping it is why
 * toggles drift out of sync with the system at sunset.
 */
export default function ThemeToggle({ className = '' }) {
  const { mode, setTheme } = useTheme()

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className={`tab-list ${className}`}
    >
      {THEME_OPTIONS.map((option) => {
        const Icon = option.icon
        const active = mode === option.value
        return (
          <button
            key={option.value}
            role="radio"
            aria-checked={active}
            className={`tab flex items-center gap-1.5 ${active ? 'is-active' : ''}`}
            onClick={() => setTheme(option.value)}
          >
            <Icon size={13} aria-hidden="true" />
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
