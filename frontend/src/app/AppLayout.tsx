import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useTheme } from './useTheme'
import { clearTokens } from '../lib/authToken'
import './AppLayout.css'

/**
 * App shell (screen-plan §0): left sidebar 264px with per-role nav,
 * production-model indicator and theme toggle; content max 1440px.
 * Nav items are placeholders until RBAC lands (FE-02).
 */
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/monitoring/live', label: 'Monitoring' },
  { to: '/monitoring/events', label: 'Access Log' },
  { to: '/users', label: 'Users' },
  { to: '/enrollments', label: 'Enrollment' },
  { to: '/models', label: 'Models & Training' },
  { to: '/devices', label: 'Devices' },
  { to: '/system-parameters', label: 'System Parameter' },
]

/** Sun icon — shown while the light theme is active (click to switch to dark). */
function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="4.5" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
        <line x1="12" y1="1.5" x2="12" y2="4" />
        <line x1="12" y1="20" x2="12" y2="22.5" />
        <line x1="1.5" y1="12" x2="4" y2="12" />
        <line x1="20" y1="12" x2="22.5" y2="12" />
        <line x1="4.4" y1="4.4" x2="6.1" y2="6.1" />
        <line x1="17.9" y1="17.9" x2="19.6" y2="19.6" />
        <line x1="4.4" y1="19.6" x2="6.1" y2="17.9" />
        <line x1="17.9" y1="6.1" x2="19.6" y2="4.4" />
      </g>
    </svg>
  )
}

/** Moon icon — shown while the dark theme is active (click to switch to light). */
function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M20.4 14.7A8.5 8.5 0 0 1 9.3 3.6a.75.75 0 0 0-.94-1A10 10 0 1 0 21.4 15.6a.75.75 0 0 0-1-.94Z"
      />
    </svg>
  )
}

export default function AppLayout() {
  const { toggle, isDark } = useTheme()
  const navigate = useNavigate()

  function handleLogout() {
    clearTokens()
    navigate('/login', { replace: true })
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-sidebar__brand">
          <span className="app-sidebar__logo" aria-hidden="true" />
          <span className="app-sidebar__title">FRAC Console</span>
        </div>
        <nav className="app-sidebar__nav" aria-label="Navigasi utama">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                isActive ? 'app-nav-link app-nav-link--active' : 'app-nav-link'
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="app-sidebar__footer">
          <p className="app-sidebar__model mono">
            model: <span className="app-badge app-badge--neutral">n/a</span>
          </p>
          <div className="app-sidebar__footer-row">
            <button
              type="button"
              className="app-theme-toggle app-theme-toggle--icon"
              onClick={toggle}
              aria-label={isDark ? 'Ganti ke tema terang' : 'Ganti ke tema gelap'}
              title={isDark ? 'Ganti ke tema terang' : 'Ganti ke tema gelap'}
            >
              {isDark ? <MoonIcon /> : <SunIcon />}
            </button>
            <button type="button" className="app-theme-toggle" onClick={handleLogout}>
              Keluar
            </button>
          </div>
        </div>
      </aside>
      <main className="app-content">
        <div className="app-content__inner">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
