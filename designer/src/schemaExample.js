/**
 * Turn a plugin's config JSON Schema into a filled-in example value — the
 * "pre-configured JSON" the step panel shows next to the JSON editor.
 *
 * Like the rest of the designer this is generic: nothing here knows about any
 * particular plugin. A plugin steers the result by declaring `examples=[...]`
 * on a pydantic Field (or `json_schema_extra={"example": ...}` on the Config
 * model); otherwise the shape is derived from defaults, enums and types, so a
 * freshly written third-party plugin still gets a usable skeleton.
 */

const MAX_DEPTH = 6

/** Resolve `{"$ref": "#/$defs/X"}`; sibling keywords (default, examples) win. */
function deref(spec, root) {
  if (!spec || typeof spec !== 'object' || typeof spec.$ref !== 'string') return spec
  const { $ref, ...siblings } = spec
  if (!$ref.startsWith('#/')) return siblings
  let target = root
  for (const part of $ref.slice(2).split('/')) {
    target = target?.[part.replace(/~1/g, '/').replace(/~0/g, '~')]
    if (target === undefined || target === null) return siblings
  }
  return { ...target, ...siblings }
}

function firstType(spec) {
  const type = spec.type
  return Array.isArray(type) ? type.find((entry) => entry !== 'null') ?? 'null' : type
}

/** Nothing worth showing: a value that carries no more information than its own absence. */
function isBlank(value) {
  if (value === null || value === undefined || value === '') return true
  return typeof value === 'object' && Object.keys(value).length === 0
}

function sample(rawSpec, root, depth) {
  const spec = deref(rawSpec, root)
  if (!spec || typeof spec !== 'object') return null
  if (Array.isArray(spec.examples) && spec.examples.length > 0) return spec.examples[0]
  if (spec.example !== undefined) return spec.example
  if (depth > MAX_DEPTH) return spec.default ?? null

  const branches = spec.anyOf ?? spec.oneOf ?? spec.allOf
  if (Array.isArray(branches) && branches.length > 0) {
    // Optional[X] is emitted as anyOf [X, null] — the interesting branch is the non-null one
    const branch = branches.find((entry) => firstType(deref(entry, root) ?? {}) !== 'null') ?? branches[0]
    const merged = { ...deref(branch, root) }
    if (spec.default !== undefined) merged.default = spec.default
    return sample(merged, root, depth + 1)
  }

  if (Array.isArray(spec.enum) && spec.enum.length > 0) return spec.default ?? spec.enum[0]

  switch (firstType(spec)) {
    case 'object': {
      if (spec.properties) {
        return Object.fromEntries(
          Object.entries(spec.properties).map(([name, child]) => [name, sample(child, root, depth + 1)]),
        )
      }
      if (spec.additionalProperties && typeof spec.additionalProperties === 'object') {
        const entry = sample(spec.additionalProperties, root, depth + 1) // dict[str, X]
        if (!isBlank(entry)) return { key: entry }
      }
      return spec.default ?? {}
    }
    case 'array': {
      const item = spec.items ? sample(spec.items, root, depth + 1) : null
      // a blank member says nothing the empty container doesn't (list[str], list[Any], …)
      return isBlank(item) ? spec.default ?? [] : [item]
    }
    case 'string':
      return spec.default ?? ''
    case 'integer':
    case 'number':
      return spec.default ?? 0
    case 'boolean':
      return spec.default ?? false
    case 'null':
      return null
    default:
      return spec.default ?? null // an untyped field (Any) — usually holds an expression
  }
}

/** Example config object for a whole plugin schema. */
export function exampleConfig(schema) {
  const value = sample(schema ?? {}, schema ?? {}, 0)
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

/**
 * Example for a single field, or undefined when nothing informative can be
 * derived — callers fall back to their own placeholder in that case.
 */
export function exampleField(spec, root) {
  const value = sample(spec ?? {}, root ?? {}, 0)
  return isBlank(value) ? undefined : value
}
