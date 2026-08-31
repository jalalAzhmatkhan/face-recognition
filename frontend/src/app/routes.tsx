import type { RouteObject } from 'react-router-dom'
import AppLayout from './AppLayout'
import AuthGuard from './AuthGuard'
import LoginPage from '../pages/LoginPage'
import SetupAdminPage from '../pages/SetupAdminPage'
import ForgotPasswordPage from '../pages/ForgotPasswordPage'
import ResetPasswordPage from '../pages/ResetPasswordPage'
import DashboardPage from '../pages/DashboardPage'
import UsersPage from '../pages/UsersPage'
import UserDetailPage from '../pages/UserDetailPage'
import EnrollmentsPage from '../pages/EnrollmentsPage'
import EnrollmentDetailPage from '../pages/EnrollmentDetailPage'
import EnrollmentCapturePage from '../features/enrollment-capture/EnrollmentCapturePage'
import MonitoringPage from '../pages/MonitoringPage'
import LiveMonitoringPage from '../features/live-monitoring/LiveMonitoringPage'
import AccessLogPage from '../pages/AccessLogPage'
import DevicesPage from '../pages/DevicesPage'
import ModelsPage from '../pages/ModelsPage'
import TrainingJobDetailPage from '../pages/TrainingJobDetailPage'
import ModelPromotionPage from '../pages/ModelPromotionPage'
import NotFoundPage from '../pages/NotFoundPage'

/**
 * Routing shell per screen-plan §1 (S-01…S-90).
 * /login lives outside the app shell; everything else inside AppLayout.
 * Deeper routes (/users/:id, /enrollments/:id/capture, /monitoring/live, …)
 * are added by FE-03..FE-09.
 */
export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  // First-run "create ADMIN account" screen -- same reasoning as /login for
  // living outside AuthGuard (see SetupAdminPage.tsx docstring).
  { path: '/setup', element: <SetupAdminPage /> },
  // Forgot/reset password -- same reasoning as /login (must be reachable
  // with no session at all).
  { path: '/forgot-password', element: <ForgotPasswordPage /> },
  { path: '/reset-password', element: <ResetPasswordPage /> },
  // S-30 capture wizard is full-screen outside the app shell (screen-plan),
  // same as /login — sidebar/nav would only distract during capture.
  { path: '/enrollments/:id/capture', element: <EnrollmentCapturePage /> },
  {
    path: '/',
    // FE-02: every route in the shell requires a valid session; see
    // AuthGuard.tsx for why this is login-only, not role-based.
    element: <AuthGuard />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'users', element: <UsersPage /> },
          { path: 'users/:id', element: <UserDetailPage /> },
          { path: 'enrollments', element: <EnrollmentsPage /> },
          { path: 'enrollments/:id', element: <EnrollmentDetailPage /> },
          { path: 'monitoring', element: <MonitoringPage /> },
          { path: 'monitoring/live', element: <LiveMonitoringPage /> },
          { path: 'monitoring/events', element: <AccessLogPage /> },
          { path: 'devices', element: <DevicesPage /> },
          { path: 'models', element: <ModelsPage /> },
          { path: 'models/jobs/:id', element: <TrainingJobDetailPage /> },
          { path: 'models/:version/promote', element: <ModelPromotionPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
