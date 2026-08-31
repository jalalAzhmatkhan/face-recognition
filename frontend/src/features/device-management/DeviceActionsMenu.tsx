import type { ReactNode } from 'react'
import ActionsMenu, { ActionsMenuConfirm, ActionsMenuItem } from '../../components/ActionsMenu'
import type { DeviceResponse } from './types'

interface DeviceActionsMenuProps {
  device: DeviceResponse
  canEdit: boolean
  canRotate: boolean
  canDisable: boolean
  anyMutationPending: boolean
  isRotateTarget: boolean
  isRotatePending: boolean
  isDisableTarget: boolean
  isDisablePending: boolean
  onEdit: () => void
  onRequestRotate: () => void
  onCancelRotate: () => void
  onConfirmRotate: () => void
  onRequestDisable: () => void
  onCancelDisable: () => void
  onConfirmDisable: () => void
}

/**
 * S-60 "Aksi" column, built on the shared `ActionsMenu` primitive (bugfix:
 * users-actions-menu, extended here). Same actions/role-gating as before
 * (Edit, Rotasi Kredensial with a warning confirm, Nonaktifkan with a
 * danger confirm) behind one "⋮" trigger per row. Only rendered when the
 * row is NOT in inline-edit mode -- `DevicesPage` swaps to a plain
 * Save/Cancel pair for that case instead, since editing changes the whole
 * row's other cells too, not just this one.
 */
export default function DeviceActionsMenu({
  device,
  canEdit,
  canRotate,
  canDisable,
  anyMutationPending,
  isRotateTarget,
  isRotatePending,
  isDisableTarget,
  isDisablePending,
  onEdit,
  onRequestRotate,
  onCancelRotate,
  onConfirmRotate,
  onRequestDisable,
  onCancelDisable,
  onConfirmDisable,
}: DeviceActionsMenuProps) {
  const canDisableThisDevice = canDisable && device.status !== 'DISABLED'
  // OPERATOR (this page's other allowed role, see roleGating.ts) has none
  // of these three actions -- show nothing at all rather than a "⋮"
  // trigger that opens an empty menu.
  if (!canEdit && !canRotate && !canDisableThisDevice && !isRotateTarget && !isDisableTarget) {
    return null
  }

  let renderConfirm: (() => ReactNode) | undefined
  if (isRotateTarget) {
    renderConfirm = () => (
      <ActionsMenuConfirm
        tone="warning"
        text="Kredensial lama akan langsung invalid — device fisik harus diupdate manual dengan kredensial baru. Lanjutkan?"
        confirmLabel="Ya, Rotasi"
        pendingLabel="Memproses..."
        isPending={isRotatePending}
        disabled={anyMutationPending}
        onConfirm={onConfirmRotate}
        onCancel={onCancelRotate}
      />
    )
  } else if (isDisableTarget) {
    renderConfirm = () => (
      <ActionsMenuConfirm
        tone="danger"
        text="Device tidak akan bisa lagi mengirim heartbeat/access-event valid (bukan hapus permanen). Yakin?"
        confirmLabel="Ya, Nonaktifkan"
        pendingLabel="Memproses..."
        isPending={isDisablePending}
        disabled={anyMutationPending}
        onConfirm={onConfirmDisable}
        onCancel={onCancelDisable}
      />
    )
  }

  return (
    <ActionsMenu renderConfirm={renderConfirm}>
      {(closeMenu) => (
        <>
          {canEdit && (
            <ActionsMenuItem
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onEdit()
              }}
            >
              Edit
            </ActionsMenuItem>
          )}

          {canRotate && (
            <ActionsMenuItem
              variant="warning"
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onRequestRotate()
              }}
            >
              Rotasi Kredensial
            </ActionsMenuItem>
          )}

          {canDisableThisDevice && (
            <ActionsMenuItem
              variant="danger"
              disabled={anyMutationPending}
              onClick={() => {
                closeMenu()
                onRequestDisable()
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
