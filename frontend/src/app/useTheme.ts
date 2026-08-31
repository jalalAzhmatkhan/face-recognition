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

function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/**
 * Theme preference (design-tokens §1): default follows prefers-color-scheme,
 * user override sets data-theme="light|dark" on <html>.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme)
  // Only relevant while `theme === 'system'` -- tracks the OS preference so
  // the sun/moon toggle icon can reflect what's actually rendered without
  // re-querying matchMedia during render.
  const [systemDark, setSystemDark] = useState<boolean>(systemPrefersDark)

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

  // While following 'system', keep systemDark in sync if the OS preference
  // changes out from under us.
  useEffect(() => {
    if (theme !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => setSystemDark(media.matches)
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [theme])

  const isDark = theme === 'dark' || (theme === 'system' && systemDark)

  const toggle = useCallback(() => {
    setTheme((current) => {
      const effectiveDark = current === 'dark' || (current === 'system' && systemPrefersDark())
      return effectiveDark ? 'light' : 'dark'
    })
  }, [])

  return { theme, setTheme, toggle, isDark }
}
