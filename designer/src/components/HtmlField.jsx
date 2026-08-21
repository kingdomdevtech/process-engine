import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  Eraser,
  Eye,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  Link2,
  Link2Off,
  List,
  ListOrdered,
  Minus,
  Pilcrow,
  Quote,
  Sparkles,
  Strikethrough,
  Type,
  Underline,
} from 'lucide-react'
import { useDialogs } from './ui/Dialogs.jsx'

const PLACEHOLDER_SNIPPETS = ['{{ trigger. }}', '{{ steps..output. }}', '{{ variables. }}', '{{ secrets. }}', '{{ input. }}']

// Content that carries its own <head>/<style>/<script> cannot survive a contentEditable
// round-trip (the browser keeps only body markup, and a live <style> would restyle the
// designer itself), so such values stay source-only.
const DOCUMENT_MARKUP = /<\s*(?:!doctype|html|head|body|style|script)\b/i

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'])

const BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer',
  'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section',
  'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'ul',
])

const UNSAFE_PASTE_TAGS = 'script,style,link,meta,title,base,iframe,object,embed,form,noscript'

// Each button drives two surfaces: `command`/`argument` run against the rich-text editor via
// execCommand; `kind`/`arg` rewrite the selection in the raw HTML textarea.
const TOOLBAR_GROUPS = [
  [
    { key: 'bold', icon: Bold, title: 'Bold (Ctrl+B)', command: 'bold', kind: 'wrap', arg: 'strong' },
    { key: 'italic', icon: Italic, title: 'Italic (Ctrl+I)', command: 'italic', kind: 'wrap', arg: 'em' },
    { key: 'underline', icon: Underline, title: 'Underline (Ctrl+U)', command: 'underline', kind: 'wrap', arg: 'u' },
    { key: 'strike', icon: Strikethrough, title: 'Strikethrough', command: 'strikeThrough', kind: 'wrap', arg: 's' },
  ],
  [
    { key: 'h1', icon: Heading1, title: 'Heading 1', command: 'formatBlock', argument: '<h1>', kind: 'block', arg: 'h1' },
    { key: 'h2', icon: Heading2, title: 'Heading 2', command: 'formatBlock', argument: '<h2>', kind: 'block', arg: 'h2' },
    { key: 'h3', icon: Heading3, title: 'Heading 3', command: 'formatBlock', argument: '<h3>', kind: 'block', arg: 'h3' },
    { key: 'p', icon: Pilcrow, title: 'Paragraph', command: 'formatBlock', argument: '<p>', kind: 'block', arg: 'p' },
    { key: 'quote', icon: Quote, title: 'Blockquote', command: 'formatBlock', argument: '<blockquote>', kind: 'block', arg: 'blockquote' },
  ],
  [
    { key: 'ul', icon: List, title: 'Bulleted list', command: 'insertUnorderedList', kind: 'list', arg: 'ul' },
    { key: 'ol', icon: ListOrdered, title: 'Numbered list', command: 'insertOrderedList', kind: 'list', arg: 'ol' },
  ],
  [
    { key: 'left', icon: AlignLeft, title: 'Align left', command: 'justifyLeft', kind: 'align', arg: 'left' },
    { key: 'center', icon: AlignCenter, title: 'Align centre', command: 'justifyCenter', kind: 'align', arg: 'center' },
    { key: 'right', icon: AlignRight, title: 'Align right', command: 'justifyRight', kind: 'align', arg: 'right' },
  ],
  [
    { key: 'link', icon: Link2, title: 'Insert link', command: 'createLink', kind: 'link' },
    { key: 'unlink', icon: Link2Off, title: 'Remove link', command: 'unlink', kind: 'unlink' },
    { key: 'hr', icon: Minus, title: 'Horizontal rule', command: 'insertHorizontalRule', kind: 'rule' },
  ],
  [
    { key: 'clear', icon: Eraser, title: 'Remove formatting', command: 'removeFormat', kind: 'clear' },
    { key: 'tidy', icon: Sparkles, title: 'Re-indent the HTML source', kind: 'tidy', sourceOnly: true },
  ],
]

const TABS = [
  { key: 'rich', label: 'Rich text', icon: Type },
  { key: 'source', label: 'HTML', icon: Code2 },
  { key: 'preview', label: 'Preview', icon: Eye },
]

const escapeText = (raw) => raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const escapeAttribute = (raw) => escapeText(raw).replace(/"/g, '&quot;')

/** javascript: URLs would execute in the preview frame and in delivered mail. */
function cleanUrl(url) {
  const trimmed = (url ?? '').trim()
  if (!trimmed || /^javascript:/i.test(trimmed)) return null
  return trimmed
}

// Pasted markup lands in the live DOM, so drop anything that could execute or leak styles
// into the designer. DOMParser builds an inert document, nothing runs here.
function sanitizePasted(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.body.querySelectorAll(UNSAFE_PASTE_TAGS).forEach((element) => element.remove())
  doc.body.querySelectorAll('*').forEach((element) => {
    for (const attribute of [...element.attributes]) {
      const isEventHandler = /^on/i.test(attribute.name)
      const isScriptUrl = /^(?:href|src)$/i.test(attribute.name) && /^\s*javascript:/i.test(attribute.value)
      if (isEventHandler || isScriptUrl) element.removeAttribute(attribute.name)
    }
  })
  return doc.body.innerHTML
}

function openingTag(element) {
  const attributes = [...element.attributes].map((a) => ` ${a.name}="${a.value.replace(/"/g, '&quot;')}"`).join('')
  return `<${element.tagName.toLowerCase()}${attributes}>`
}

// Conservative pretty-printer: only blocks that contain other blocks get expanded, everything
// else is emitted verbatim, so inline markup and <pre> keep their exact whitespace.
function printNode(node, depth, out) {
  const pad = '  '.repeat(depth)
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.textContent.replace(/\s+/g, ' ').trim()
    if (text) out.push(pad + text)
    return
  }
  if (node.nodeType === Node.COMMENT_NODE) {
    out.push(`${pad}<!--${node.textContent}-->`)
    return
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return
  const tag = node.tagName.toLowerCase()
  if (VOID_TAGS.has(tag)) {
    out.push(pad + openingTag(node))
    return
  }
  const hasBlockChild = [...node.childNodes].some((c) => c.nodeType === Node.ELEMENT_NODE && BLOCK_TAGS.has(c.tagName.toLowerCase()))
  if (tag === 'pre' || !hasBlockChild) {
    out.push(pad + node.outerHTML)
    return
  }
  out.push(pad + openingTag(node))
  node.childNodes.forEach((child) => printNode(child, depth + 1, out))
  out.push(`${pad}</${tag}>`)
}

function tidyHtml(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const out = []
  doc.body.childNodes.forEach((child) => printNode(child, 0, out))
  return out.join('\n')
}

// Returns the replacement for the current textarea selection plus the offsets, relative to
// that replacement, the caret/selection should end up at.
function buildSourceEdit(button, selected, url) {
  switch (button.kind) {
    case 'wrap':
    case 'block': {
      const open = `<${button.arg}>`
      return { text: `${open}${selected}</${button.arg}>`, from: open.length, to: open.length + selected.length }
    }
    case 'list': {
      const lines = selected.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
      const items = (lines.length ? lines : ['']).map((line) => `  <li>${line}</li>`).join('\n')
      const open = `<${button.arg}>\n`
      return { text: `${open}${items}\n</${button.arg}>`, from: open.length, to: open.length + items.length }
    }
    case 'align': {
      const open = `<div style="text-align: ${button.arg}">`
      return { text: `${open}${selected}</div>`, from: open.length, to: open.length + selected.length }
    }
    case 'link': {
      if (!url) return null
      const open = `<a href="${escapeAttribute(url)}">`
      const inner = selected || escapeText(url)
      return { text: `${open}${inner}</a>`, from: open.length, to: open.length + inner.length }
    }
    case 'unlink': {
      const text = selected.replace(/<a\b[^>]*>/gi, '').replace(/<\/a\s*>/gi, '')
      return { text, from: 0, to: text.length }
    }
    case 'rule': {
      const text = '<hr />'
      return { text, from: text.length, to: text.length }
    }
    case 'clear': {
      const text = selected.replace(/<[^>]*>/g, '')
      return { text, from: 0, to: text.length }
    }
    default:
      return null
  }
}

export default function HtmlField({ value, onCommit, id }) {
  const [text, setText] = useState(value ?? '')
  const [tab, setTab] = useState(() => (DOCUMENT_MARKUP.test(value ?? '') ? 'source' : 'rich'))
  const [active, setActive] = useState({})
  const editorRef = useRef(null)
  const areaRef = useRef(null)
  const pendingSelection = useRef(null)
  const lastCommitted = useRef(value ?? '')
  const savedRange = useRef(null)
  const dialogs = useDialogs()

  const isDocument = DOCUMENT_MARKUP.test(text)

  const commit = (next) => {
    lastCommitted.current = next
    onCommit(next === '' ? undefined : next)
  }

  // The config can also be rewritten from outside — the ƒx data picker appends to it, and the
  // JSON tab replaces it wholesale. Adopt those, but ignore the echo of our own commits.
  useEffect(() => {
    const incoming = value ?? ''
    if (incoming === lastCommitted.current) return
    lastCommitted.current = incoming
    setText(incoming)
  }, [value])

  const update = (next) => {
    setText(next)
    commit(next)
  }

  const pushFromEditor = () => {
    const element = editorRef.current
    if (!element) return
    // Chrome leaves a stray <br> behind once the last character is deleted.
    update(element.innerHTML === '<br>' ? '' : element.innerHTML)
  }

  const readActive = useCallback(() => {
    const element = editorRef.current
    const selection = window.getSelection()
    if (!element || !selection?.anchorNode || !element.contains(selection.anchorNode)) return
    const next = {}
    let block = ''
    try {
      block = String(document.queryCommandValue('formatBlock') || '').toLowerCase()
    } catch {
      block = ''
    }
    for (const button of TOOLBAR_GROUPS.flat()) {
      if (button.kind === 'block') {
        next[button.key] = button.arg === block
      } else if (button.command && button.kind !== 'link') {
        try {
          next[button.key] = document.queryCommandState(button.command)
        } catch {
          next[button.key] = false
        }
      }
    }
    setActive(next)
  }, [])

  useEffect(() => {
    if (tab !== 'rich') return undefined
    try {
      // Emit tags (<b>, align="center") rather than inline CSS — far friendlier to email clients.
      document.execCommand('styleWithCSS', false, false)
      document.execCommand('defaultParagraphSeparator', false, 'p')
    } catch {
      // not supported everywhere; formatting still works
    }
    document.addEventListener('selectionchange', readActive)
    return () => document.removeEventListener('selectionchange', readActive)
  }, [tab, readActive])

  // Only write into the editor when the value diverged from what it already shows, otherwise
  // every keystroke would reset the caret to the start.
  useEffect(() => {
    if (tab !== 'rich') return
    const element = editorRef.current
    if (element && element.innerHTML !== text) element.innerHTML = text
  }, [tab, text])

  useEffect(() => {
    const pending = pendingSelection.current
    if (!pending) return
    pendingSelection.current = null
    const area = areaRef.current
    if (!area) return
    area.focus()
    area.setSelectionRange(pending[0], pending[1])
  })

  /* Opening the link dialog moves focus out of the editor, which collapses the
     selection the command needs. Stash the range first and put it back after. */
  const rememberSelection = () => {
    const selection = window.getSelection()
    savedRange.current =
      selection?.rangeCount && editorRef.current?.contains(selection.anchorNode)
        ? selection.getRangeAt(0).cloneRange()
        : null
  }

  const restoreSelection = () => {
    const selection = window.getSelection()
    if (!savedRange.current || !selection) return
    selection.removeAllRanges()
    selection.addRange(savedRange.current)
    savedRange.current = null
  }

  const askForUrl = () =>
    dialogs
      .prompt({
        title: 'Insert link',
        label: 'URL',
        defaultValue: 'https://',
        confirmLabel: 'Insert',
        hint: 'Opened by the recipient — use an absolute URL.',
      })
      .then(cleanUrl)

  const applyRich = (button, url) => {
    const element = editorRef.current
    if (!element) return
    element.focus()
    if (button.kind === 'link') {
      restoreSelection()
      const selection = window.getSelection()
      if (selection && !selection.isCollapsed) {
        document.execCommand('createLink', false, url)
      } else {
        document.execCommand('insertHTML', false, `<a href="${escapeAttribute(url)}">${escapeText(url)}</a>`)
      }
    } else {
      document.execCommand(button.command, false, button.argument)
    }
    pushFromEditor()
    readActive()
  }

  const applySource = (button, url, range) => {
    const area = areaRef.current
    if (!area) return
    const current = area.value
    const [start, end] = range ?? [area.selectionStart, area.selectionEnd]
    const built = buildSourceEdit(button, current.slice(start, end), url)
    if (!built) return
    update(current.slice(0, start) + built.text + current.slice(end))
    pendingSelection.current = [start + built.from, start + built.to]
  }

  const apply = async (button) => {
    if (button.kind === 'tidy') {
      update(tidyHtml(text))
      return
    }
    if (button.kind === 'link') {
      // capture the target before the dialog steals focus
      const range = tab === 'source' ? [areaRef.current?.selectionStart ?? 0, areaRef.current?.selectionEnd ?? 0] : null
      if (tab === 'rich') rememberSelection()
      const url = await askForUrl()
      if (!url) return
      if (tab === 'rich') applyRich(button, url)
      else applySource(button, url, range)
      return
    }
    if (tab === 'rich') applyRich(button)
    else applySource(button)
  }

  const insertSnippet = (snippet) => {
    if (tab === 'rich') {
      const element = editorRef.current
      if (!element) return
      element.focus()
      document.execCommand('insertText', false, snippet)
      pushFromEditor()
      return
    }
    const area = areaRef.current
    if (!area) return
    const { value: current, selectionStart: start, selectionEnd: end } = area
    update(current.slice(0, start) + snippet + current.slice(end))
    pendingSelection.current = [start + snippet.length, start + snippet.length]
  }

  const handlePaste = (event) => {
    const html = event.clipboardData?.getData('text/html')
    const plain = event.clipboardData?.getData('text/plain')
    if (!html && !plain) return
    event.preventDefault()
    if (html) document.execCommand('insertHTML', false, sanitizePasted(html))
    else document.execCommand('insertText', false, plain)
    pushFromEditor()
  }

  return (
    <div>
      <div className="tab-list mb-1.5 w-full" role="tablist" aria-label="Editing mode">
        {TABS.map((entry) => {
          const Icon = entry.icon
          const disabled = entry.key === 'rich' && isDocument
          return (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={tab === entry.key}
              disabled={disabled}
              title={
                disabled ? 'Unavailable: this value is a full HTML document' : `Edit as ${entry.label.toLowerCase()}`
              }
              className={`tab flex flex-1 items-center justify-center gap-1 ${tab === entry.key ? 'is-active' : ''} ${
                disabled ? 'opacity-40' : ''
              }`}
              onClick={() => setTab(entry.key)}
            >
              <Icon size={12} aria-hidden="true" />
              {entry.label}
            </button>
          )
        })}
      </div>

      {tab === 'preview' ? (
        // sandbox="" — no scripts, no same-origin access, nothing from the value can run
        <iframe
          className="min-h-44 w-full rounded-md border border-line bg-white"
          sandbox=""
          title="HTML preview"
          // The iframe is a separate document and cannot see our custom
          // properties, so this is --fg-subtle's light value written out. It
          // stays light-mode because the frame is deliberately white: this
          // previews an email, and mail clients render on white.
          srcDoc={text || '<p style="color:#656c78;font-family:sans-serif">Nothing to preview yet.</p>'}
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-x-1.5 gap-y-1 rounded-t-md border border-b-0 border-line bg-surface-2 p-1">
            {TOOLBAR_GROUPS.map((group, index) => {
              const buttons = group.filter((button) => tab === 'source' || !button.sourceOnly)
              if (buttons.length === 0) return null
              return (
                <div
                  key={index}
                  className="flex gap-0.5 [&+div]:border-l [&+div]:border-line [&+div]:pl-1.5"
                >
                  {buttons.map((button) => {
                    const Icon = button.icon
                    const isActive = tab === 'rich' && active[button.key]
                    return (
                      <button
                        key={button.key}
                        type="button"
                        title={button.title}
                        aria-label={button.title}
                        aria-pressed={isActive || undefined}
                        disabled={button.kind === 'tidy' && isDocument}
                        className={`grid size-6 place-items-center rounded border border-transparent text-fg-muted transition-colors hover:bg-surface-3 hover:text-fg disabled:pointer-events-none disabled:opacity-40 ${
                          isActive ? 'border-brand bg-brand-soft text-brand-text' : ''
                        }`}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => apply(button)}
                      >
                        <Icon size={13} />
                      </button>
                    )
                  })}
                </div>
              )
            })}
          </div>

          {tab === 'rich' ? (
            <div
              id={id}
              ref={editorRef}
              className="rich-content max-h-80 min-h-44 w-full overflow-y-auto rounded-b-md border border-line bg-surface px-3 py-2 focus:border-brand focus:outline-none focus:ring-2 focus:ring-ring/25"
              contentEditable
              spellCheck
              role="textbox"
              aria-multiline="true"
              aria-label="Message body"
              data-placeholder="Write the message, select text and use the toolbar to format it."
              onInput={pushFromEditor}
              onPaste={handlePaste}
              onBlur={pushFromEditor}
            />
          ) : (
            <textarea
              id={id}
              ref={areaRef}
              className="textarea min-h-44 rounded-t-none"
              value={text}
              spellCheck={false}
              aria-label="Message body, HTML source"
              placeholder="<h1>Hello {{ trigger.name }}</h1><p>Your order {{ steps.fetch.output.id }} shipped.</p>"
              onChange={(event) => update(event.target.value)}
            />
          )}

          <div className="mt-1.5 flex flex-wrap gap-1">
            {PLACEHOLDER_SNIPPETS.map((snippet) => (
              <button
                key={snippet}
                type="button"
                className="badge font-mono font-normal hover:bg-brand-soft hover:text-brand-text"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => insertSnippet(snippet)}
              >
                {snippet}
              </button>
            ))}
          </div>

          {isDocument && (
            <p className="hint mt-1.5">
              Full HTML document — rich text editing is off so {'<head>'} and {'<style>'} are not dropped.
            </p>
          )}
        </>
      )}
    </div>
  )
}
