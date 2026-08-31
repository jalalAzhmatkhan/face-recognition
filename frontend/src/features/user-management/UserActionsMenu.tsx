import ActionsMenu, { ActionsMenuConfirm, ActionsMenuItem } from '../../components/ActionsMenu'
import type { UserResponse, UserStatus } from './types'

interface UserActionsMenuProps {
  user: UserResponse
  canQuickChangeStatus: boolean
  canOffboard: boolean
  canEnroll: boolean
  anyMutationPending: boolean
  isOffboardTarget: boolean
  isOffboardPending: boolean
  onStatusChange: (status: UserStatus) => void
  onRequestOffboard: () => void
  onCancelOffboard: () => void
  onConfirmOffboard: () => void
  onEnroll: () => void
}

/**
 * S-10 "Aksi" column, built on the shared `ActionsMenu` primitive (bugfix:
 * users-actions-menu). Same actions/role-gating as before (Detail/Edit,
 * Suspend/Aktifkan, Mulai Enrollment, Nonaktifkan with a confirm step),
 * just tucked behind a single "⋮" trigger per row instead of several
 * always-visible buttons.
 */
export default function UserActionsMenu({
  user,
  canQuickChangeStatus,
  canOffboard,
  canEnroll,
  anyMutationPending,
  isOffboardTarget,
  isOffboardPending,
  onStatusChange,
  onRequestOffboard,
  onCancelOffboard,
  onConfirmOffboard,
  onEnroll,
}: UserActionsMenuProps) {
  return (
    <ActionsMenu
      renderConfirm={
        isOffboardTarget
          ? () => (
              <ActionsMenuConfirm
                tone="danger"
                text="Yakin nonaktifkan user ini?"
                confirmLabel="Ya, Nonaktifkan"
                pendingLabel="Memproses..."
                isPending={isOffboardPending}
                disabled={anyMutationPending}
                onConfirm={onConfirmOffboard}
                onCancel={onCancelOffboard}
              />
            )
          : undefined
      }
    >
      {(closeMenu) => (
        <>
          <ActionsMenuItem to={`/users/${user.id}`}>Detail / Edit</ActionsMenuItem>

          {canQuickChangeStatus && user.status === 'ACTIVE' && (
            <ActionsMenuItem
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onStatusChange('SUSPENDED')
              }}
            >
              Suspend
            </ActionsMenuItem>
          )}

          {canQuickChangeStatus && user.status === 'SUSPENDED' && (
            <ActionsMenuItem
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onStatusChange('ACTIVE')
              }}
            >
              Aktifkan
            </ActionsMenuItem>
          )}

          {canEnroll && (
            <ActionsMenuItem
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onEnroll()
              }}
            >
              Mulai Enrollment
            </ActionsMenuItem>
          )}

          {canOffboard && user.status !== 'OFFBOARDED' && (
            <ActionsMenuItem
              variant="danger"
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onRequestOffboard()
              }}
            >
              Nonaktifkan
            </ActionsMenuItem>
          )}
        </>
      )}
    </ActionsMenu>
  )
}
