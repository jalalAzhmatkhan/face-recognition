import type { RouteObject } from 'react-router-dom'
import AppLayout from './AppLayout'
import LoginPage from '../pages/LoginPage'
import DashboardPage from '../pages/DashboardPage'
import UsersPage from '../pages/UsersPage'
import EnrollmentsPage from '../pages/EnrollmentsPage'
import MonitoringPage from '../pages/MonitoringPage'
import DevicesPage from '../pages/DevicesPage'
import ModelsPage from '../pages/ModelsPage'
import NotFoundPage from '../pages/NotFoundPage'

/**
 * Routing shell per screen-plan §1 (S-01…S-90).
 * /login lives outside the app shell; everything else inside AppLayout.
 * Deeper routes (/users/:id, /enrollments/:id/capture, /monitoring/live, …)
 * are added by FE-03..FE-09.
 */
export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'users', element: <UsersPage /> },
      { path: 'enrollments', element: <EnrollmentsPage /> },
      { path: 'monitoring', element: <MonitoringPage /> },
      { path: 'devices', element: <DevicesPage /> },
      { path: 'models', element: <ModelsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
