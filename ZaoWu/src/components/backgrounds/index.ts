interface BgMeta {
  id: string
  name: string
  defaultParams: Record<string, unknown>
}

interface BgEntry {
  component: unknown
  meta: BgMeta
}

const modules = import.meta.glob('./*.vue', { eager: true })

export const backgroundRegistry: BgEntry[] = Object.entries(modules)
  .filter(([path]) => !path.endsWith('index.ts') && !path.includes('BackgroundManager'))
  .map(([_path, mod]) => {
    const m = mod as Record<string, unknown>
    let meta: BgMeta | undefined

    if (typeof m.bgMeta === 'object' && m.bgMeta !== null) {
      meta = m.bgMeta as BgMeta
    }

    if (!meta) {
      const name = _path.replace('./', '').replace('.vue', '')
      meta = { id: name.toLowerCase(), name, defaultParams: {} }
    }

    return {
      component: (m.default as BgEntry['component']) ?? m,
      meta,
    }
  })

export function getBackground(id: string): BgEntry | undefined {
  return backgroundRegistry.find(b => b.meta.id === id)
}
