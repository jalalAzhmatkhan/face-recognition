import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'frac-theme'

function readStoredTheme(): Theme {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark') return value
  } catch {
    /* storage unavailable — fall back to system */
  }
  return 'system'
}

/**
 * Theme preference (design-tokens §1): default follows prefers-color-scheme,
 * user override sets data-theme="light|dark" on <html>.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') {
      root.removeAttribute('data-theme')
    } else {
      root.setAttribute('data-theme', theme)
    }
    try {
      if (theme === 'system') window.localStorage.removeItem(STORAGE_KEY)
      else window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => {
      const systemDark =
        window.matchMedia('(prefers-color-scheme: dark)').matches
      const effectiveDark =
        current === 'dark' || (current === 'system' && systemDark)
      return effectiveDark ? 'light' : 'dark'
    })
  }, [])

  return { theme, setTheme, toggle }
}
