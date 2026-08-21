import {
  Braces,
  Clock,
  CloudDownload,
  Database,
  FileSpreadsheet,
  Folder,
  Globe,
  GitBranch,
  Mail,
  Puzzle,
  Repeat,
  ScrollText,
  Shuffle,
  Table,
  Trash2,
  Wrench,
  Zap,
} from 'lucide-react'

/**
 * Presentation for a plugin: an icon and a category tint.
 *
 * The engine's plugin manifest is deliberately UI-free, and the designer builds
 * itself from that manifest — so this is a *fallback* lookup, not a registry.
 * Anything unknown (a drop-in file, a pip-installed plugin) resolves through
 * its category, and finally to a neutral puzzle piece. No plugin ever has to
 * ship frontend code to look right.
 */
const BY_KEY = {
  azure_blob_download: CloudDownload,
  condition: GitBranch,
  delay: Clock,
  excel_refresh: FileSpreadsheet,
  file_purge: Trash2,
  for_each: Repeat,
  html_table: Table,
  http_request: Globe,
  log: ScrollText,
  mysql_execute: Database,
  mysql_query: Database,
  s3_download: CloudDownload,
  send_email_ses: Mail,
  send_email_smtp: Mail,
  transform: Shuffle,
}

const BY_CATEGORY = {
  communication: Mail,
  data: Braces,
  database: Database,
  files: Folder,
  flow: Repeat,
  logic: GitBranch,
  network: Globe,
  utility: Wrench,
  trigger: Zap,
}

/* Tints come from the `cat-*` scale, which is separate from the status scale
   and deliberately about a third of its chroma. Categories are an aid to
   scanning, not a signal — nothing in the product depends on telling teal from
   violet, so they never have to compete with success/failure for attention.
   Categories with no real distinction to draw share a hue: flow and logic are
   both the graph steering itself, so both are green. */
const NEUTRAL_TINT = 'text-fg-muted bg-surface-3'

const TINTS = {
  communication: 'text-cat-rose-fg bg-cat-rose-bg',
  data: 'text-cat-violet-fg bg-cat-violet-bg',
  database: 'text-cat-teal-fg bg-cat-teal-bg',
  files: 'text-cat-amber-fg bg-cat-amber-bg',
  flow: 'text-cat-green-fg bg-cat-green-bg',
  logic: 'text-cat-green-fg bg-cat-green-bg',
  network: 'text-cat-blue-fg bg-cat-blue-bg',
  utility: NEUTRAL_TINT,
}

export function pluginIcon(plugin) {
  if (!plugin) return Puzzle
  return BY_KEY[plugin.key] ?? BY_CATEGORY[plugin.category] ?? Puzzle
}

export function pluginTint(plugin) {
  return TINTS[plugin?.category] ?? NEUTRAL_TINT
}

/** Icon in its tinted tile — the palette, the canvas node and the inspector
 *  all use this so a step is recognisable at a glance in every context. The
 *  tile is safe on the canvas because the cat-* scale runs at a third of
 *  status chroma: run state (the node's coloured ring) always outshouts it. */
export function PluginIcon({ plugin, size = 14, className = '' }) {
  const Icon = pluginIcon(plugin)
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-md ${pluginTint(plugin)} ${className}`}
      aria-hidden="true"
    >
      <Icon size={size} />
    </span>
  )
}
