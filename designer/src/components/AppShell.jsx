import { useCallback, useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  ChevronsLeft,
  ChevronsRight,
  Compass,
  Keyboard,
  LayoutDashboard,
  ListChecks,
  Lock,
  LogOut,
  Menu as MenuIcon,
  Monitor,
  Moon,
  Search,
  Settings,
  Sun,
  X,
} from 'lucide-react'

import { clearSession, getUser } from '../api.js'
import { useTheme } from '../theme.js'
import { startTour } from '../tour.js'
import CommandPalette from './CommandPalette.jsx'
import Logo from './Logo.jsx'
import Tour from './Tour.jsx'
import Menu, { MenuItem, MenuLabel, MenuSeparator } from './ui/Menu.jsx'
import Modal from './ui/Modal.jsx'
import Tooltip from './ui/Tooltip.jsx'

// Settings configures the deployment, so it is admin-only. Secrets is not:
// it is material an editor reaches for while building a step, which is why it
// sits alongside Processes rather than inside Settings.
const NAV = [
  { to: '/app', label: 'Processes', icon: LayoutDashboard, end: true },
  { to: '/app/runs', label: 'Runs', icon: ListChecks },
  { to: '/app/secrets', label: 'Secrets', icon: Lock },
  { to: '/app/settings', label: 'Settings', icon: Settings, adminOnly: true },
]

const SHORTCUTS = [
  { keys: ['Ctrl', 'K'], action: 'Open the command palette' },
  { keys: ['Ctrl', 'S'], action: 'Save the open process' },
  { keys: ['Ctrl', 'Enter'], action: 'Run the open process as a draft' },
  { keys: ['Ctrl', 'Z'], action: 'Undo a canvas change' },
  { keys: ['Ctrl', 'Shift', 'Z'], action: 'Redo a canvas change' },
  { keys: ['Ctrl', 'Shift', 'L'], action: 'Tidy up the steps on the canvas' },
  { keys: ['Del'], action: 'Delete the selected step or connection' },
  { keys: ['['], action: 'Collapse or expand the sidebar' },
  { keys: ['?'], action: 'Show this list' },
]

const COLLAPSED_KEY = 'pe_sidebar_collapsed'
const THEME_ITEMS = [
  { value: 'light', label: 'Light', icon: <Sun size={15} /> },
  { value: 'dark', label: 'Dark', icon: <Moon size={15} /> },
  { value: 'system', label: 'System', icon: <Monitor size={15} /> },
]

export default function AppShell({ title, breadcrumb, actions, children, bare = false }) {
  const navigate = useNavigate()
  const user = getUser()
  const isAdmin = user?.role === 'admin'
  const nav = NAV.filter((item) => !item.adminOnly || isAdmin)
  const initial = (user?.username ?? '?').trim().charAt(0).toUpperCase()
  const { mode, setTheme } = useTheme()

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [drawer, setDrawer] = useState(false)
  const [palette, setPalette] = useState(false)
  const [shortcuts, setShortcuts] = useState(false)

  const toggleSidebar = useCallback(() => {
    setCollapsed((current) => {
      localStorage.setItem(COLLAPSED_KEY, current ? '0' : '1')
      return !current
    })
  }, [])

  /* App-wide shortcuts. Typing in a field never triggers them, so "?" in a
     search box searches instead of opening help. */
  useEffect(() => {
    const onKeyDown = (event) => {
      const inField =
        event.target instanceof HTMLElement &&
        (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName) || event.target.isContentEditable)

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPalette((open) => !open)
        return
      }
      if (inField) return
      if (event.key === '?') {
        event.preventDefault()
        setShortcuts(true)
      } else if (event.key === '[') {
        event.preventDefault()
        toggleSidebar()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [toggleSidebar])

  const signOut = () => {
    clearSession()
    navigate('/login')
  }

  const sidebar = (
    <>
      <div className={`flex items-center gap-1 px-2 pb-4 pt-1 ${collapsed ? 'flex-col' : ''}`}>
        <Logo showName={!collapsed} size={26} />
        <button
          className={`btn btn-ghost btn-icon btn-sm ${collapsed ? '' : 'ml-auto'} max-lg:hidden`}
          onClick={toggleSidebar}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          title={`${collapsed ? 'Expand' : 'Collapse'} sidebar  [`}
        >
          {collapsed ? <ChevronsRight size={15} /> : <ChevronsLeft size={15} />}
        </button>
        <button
          className="btn btn-ghost btn-icon btn-sm ml-auto lg:hidden"
          onClick={() => setDrawer(false)}
          aria-label="Close navigation"
        >
          <X size={16} />
        </button>
      </div>

      {!collapsed && <div className="section-label px-2.5">Workspace</div>}
      {collapsed && <div className="mx-2 mb-2 h-px bg-line" />}

      <nav className="flex flex-col gap-0.5" aria-label="Main" data-tour="nav">
        {nav.map((item) => {
          const Icon = item.icon
          const link = (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => setDrawer(false)}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'is-active' : ''} ${collapsed ? 'justify-center px-0' : ''}`
              }
            >
              <Icon size={16} className="shrink-0" aria-hidden="true" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          )
          return collapsed ? (
            <Tooltip key={item.to} label={item.label} side="right">
              {link}
            </Tooltip>
          ) : (
            link
          )
        })}
      </nav>

      <div className="mt-auto border-t border-line pt-2">
        <Menu
          align="start"
          label="Account menu"
          className="w-full"
          trigger={
            <span
              className={`nav-item w-full cursor-pointer ${collapsed ? 'justify-center px-0' : ''}`}
              title={user?.username ?? 'Signed in'}
              data-tour="account"
            >
              <span
                className="brand-tile grid size-7 shrink-0 place-items-center rounded-full text-[11px] font-bold"
                aria-hidden="true"
              >
                {initial}
              </span>
              {!collapsed && (
                <span className="min-w-0 flex-1 text-left">
                  <span className="block truncate text-[13px] font-semibold text-fg">
                    {user?.username ?? 'Signed in'}
                  </span>
                  <span className="block truncate text-[11px] text-fg-subtle">{user?.role ?? ''}</span>
                </span>
              )}
            </span>
          }
        >
          <MenuLabel>Theme</MenuLabel>
          {THEME_ITEMS.map((item) => (
            <MenuItem
              key={item.value}
              icon={item.icon}
              onClick={() => setTheme(item.value)}
              aria-checked={mode === item.value}
              className={mode === item.value ? 'bg-surface-2 font-semibold' : ''}
            >
              {item.label}
            </MenuItem>
          ))}
          <MenuSeparator />
          {isAdmin && (
            <MenuItem icon={<Settings size={15} />} onClick={() => navigate('/app/settings')}>
              Settings
            </MenuItem>
          )}
          <MenuItem icon={<Compass size={15} />} onClick={() => startTour()}>
            Guided tour
          </MenuItem>
          <MenuItem icon={<Keyboard size={15} />} onClick={() => setShortcuts(true)}>
            Keyboard shortcuts
          </MenuItem>
          <MenuSeparator />
          <MenuItem icon={<LogOut size={15} />} danger onClick={signOut}>
            Sign out
          </MenuItem>
        </Menu>
      </div>
    </>
  )

  return (
    <div className="flex h-full">
      <a
        href="#pe-main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-md focus:bg-brand focus:px-3 focus:py-2 focus:text-[13px] focus:font-semibold focus:text-on-brand"
      >
        Skip to content
      </a>

      {/* Desktop rail */}
      <aside
        className={`flex shrink-0 flex-col border-r border-line bg-surface p-2 transition-[width] duration-150 max-lg:hidden ${
          collapsed ? 'w-sidebar-rail' : 'w-sidebar'
        }`}
      >
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="animate-fade absolute inset-0 bg-overlay" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-sidebar flex-col border-r border-line bg-surface p-2 shadow-xl">
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-topbar shrink-0 items-center gap-2 border-b border-line bg-surface px-3 lg:px-4">
          <button
            className="btn btn-ghost btn-icon lg:hidden"
            onClick={() => setDrawer(true)}
            aria-label="Open navigation"
          >
            <MenuIcon size={18} />
          </button>

          {breadcrumb ? (
            <div className="flex min-w-0 items-center gap-1.5 text-[13px] text-fg-muted">{breadcrumb}</div>
          ) : (
            <h1 className="truncate text-[15px] font-semibold">{title}</h1>
          )}

          <div className="ml-auto flex items-center gap-2">
            <button
              className="btn btn-ghost hidden items-center gap-2 text-fg-subtle md:inline-flex"
              onClick={() => setPalette(true)}
              aria-label="Search (Ctrl+K)"
              data-tour="search"
            >
              <Search size={15} />
              <span className="text-xs">Search</span>
              <kbd className="kbd">Ctrl K</kbd>
            </button>
            <button
              className="btn btn-ghost btn-icon md:hidden"
              onClick={() => setPalette(true)}
              aria-label="Search"
            >
              <Search size={16} />
            </button>
            {actions && <div className="flex items-center gap-2">{actions}</div>}
          </div>
        </header>

        <main id="pe-main" className="flex min-h-0 flex-1 flex-col">
          {bare ? children : <div className="flex-1 overflow-y-auto px-4 py-5 lg:px-6">{children}</div>}
        </main>
      </div>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />

      {/* Above the router's pages, so a step can walk from one screen to the next. */}
      <Tour />

      <Modal
        open={shortcuts}
        onClose={() => setShortcuts(false)}
        title="Keyboard shortcuts"
        description="Ctrl is ⌘ on macOS."
        icon={
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text">
            <Keyboard size={18} />
          </span>
        }
      >
        <dl className="divide-y divide-line">
          {SHORTCUTS.map((entry) => (
            <div key={entry.action} className="flex items-center justify-between gap-4 py-2">
              <dt className="text-[13px] text-fg-muted">{entry.action}</dt>
              <dd className="flex shrink-0 items-center gap-1">
                {entry.keys.map((key) => (
                  <kbd key={key} className="kbd">
                    {key}
                  </kbd>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </Modal>
    </div>
  )
}
