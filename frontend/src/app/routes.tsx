import type { RouteObject } from 'react-router-dom'
import AppLayout from './AppLayout'
import LoginPage from '../pages/LoginPage'
import DashboardPage from '../pages/DashboardPage'
import UsersPage from '../pages/UsersPage'
import UserDetailPage from '../pages/UserDetailPage'
import EnrollmentsPage from '../pages/EnrollmentsPage'
import EnrollmentDetailPage from '../pages/EnrollmentDetailPage'
import EnrollmentCapturePage from '../features/enrollment-capture/EnrollmentCapturePage'
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
  // S-30 capture wizard is full-screen outside the app shell (screen-plan),
  // same as /login — sidebar/nav would only distract during capture.
  { path: '/enrollments/:id/capture', element: <EnrollmentCapturePage /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'users', element: <UsersPage /> },
      { path: 'users/:id', element: <UserDetailPage /> },
      { path: 'enrollments', element: <EnrollmentsPage /> },
      { path: 'enrollments/:id', element: <EnrollmentDetailPage /> },
      { path: 'monitoring', element: <MonitoringPage /> },
      { path: 'devices', element: <DevicesPage /> },
      { path: 'models', element: <ModelsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
