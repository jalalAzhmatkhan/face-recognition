import { NavLink, Outlet } from 'react-router-dom'
import { useTheme } from './useTheme'
import './AppLayout.css'

/**
 * App shell (screen-plan §0): left sidebar 264px with per-role nav,
 * production-model indicator and theme toggle; content max 1440px.
 * Nav items are placeholders until RBAC lands (FE-02).
 */
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/monitoring', label: 'Monitoring' },
  { to: '/users', label: 'Users' },
  { to: '/enrollments', label: 'Enrollment' },
  { to: '/models', label: 'Models & Training' },
  { to: '/devices', label: 'Devices' },
]

export default function AppLayout() {
  const { toggle } = useTheme()

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
          <button
            type="button"
            className="app-theme-toggle"
            onClick={toggle}
            aria-label="Ganti tema terang/gelap"
          >
            Ganti tema
          </button>
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
