import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  createDevice,
  describeApiError,
  disableDevice,
  listDevices,
  rotateDeviceCredential,
  updateDevice,
} from '../features/device-management/api'
import {
  canActivateDevice,
  canCreateDevice,
  canDisableDevice,
  canEditDevice,
  canReadDevices,
  canRotateDeviceCredential,
} from '../features/device-management/roleGating'
import DeviceStatusBadge from '../features/device-management/DeviceStatusBadge'
import DeviceActionsMenu from '../features/device-management/DeviceActionsMenu'
import CredentialBootstrapDialog from '../features/device-management/CredentialBootstrapDialog'
import ActivateDeviceDialog from '../features/device-management/ActivateDeviceDialog'
import CommissioningChecklistDialog from '../features/device-management/CommissioningChecklistDialog'
import { DEVICE_STATUSES } from '../features/device-management/types'
import type { DeviceResponse, DeviceStatus, DeviceWithCredential } from '../features/device-management/types'
import { getCurrentRole } from '../lib/authToken'
// Reused as-is per FE-08 task instructions ("PAKAI ULANG, jangan tulis
// ulang") — no changes made to FE-06's `live-monitoring` module.
import { formatRelativeTime } from '../features/live-monitoring/relativeTime'
import '../features/device-management/DeviceManagement.css'

const PAGE_SIZE = 20

/** A row is highlighted per screen-plan S-60 ("Offline > threshold -> baris
 * ter-highlight warning") whenever it's not genuinely online right now —
 * either the DB status itself isn't ONLINE (OFFLINE; DISABLED is excluded
 * since that's an intentional admin action, not an outage worth flagging),
 * or it is ONLINE but the heartbeat has gone stale. */
function isWarningRow(device: DeviceResponse): boolean {
  if (device.status === 'DISABLED') return false
  return device.status !== 'ONLINE' || device.is_stale
}

/** S-60 device registry: list/filter/paginate, create (ADMIN, with one-time
 * credential bootstrap), edit, rotate credential, and disable (soft-delete)
 * devices. FE-08 scope. VIEWER has no access to this screen at all (unlike
 * S-40 Live Monitoring, which VIEWER may read) — see
 * `features/device-management/roleGating.ts` docstring. */
export default function DevicesPage() {
  const queryClient = useQueryClient()
  const role = getCurrentRole()
  const allowed = canReadDevices(role)

  const [statusFilter, setStatusFilter] = useState<DeviceStatus | ''>('')
  const [doorGroupFilter, setDoorGroupFilter] = useState('')
  const [offset, setOffset] = useState(0)

  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDoorGroup, setNewDoorGroup] = useState('')

  const [editTargetId, setEditTargetId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDoorGroup, setEditDoorGroup] = useState('')

  const [rotateTargetId, setRotateTargetId] = useState<string | null>(null)
  const [disableTargetId, setDisableTargetId] = useState<string | null>(null)
  const [activateTarget, setActivateTarget] = useState<{ id: string; name: string } | null>(null)
  const [checklistTarget, setChecklistTarget] = useState<DeviceResponse | null>(null)

  /** Set right after a successful create/rotate, and cleared ONLY by the
   * dialog's explicit acknowledge button (never by any other state change)
   * so the one-time credential can't accidentally disappear before the
   * operator has copied it down. */
  const [credentialReveal, setCredentialReveal] = useState<{
    deviceName: string
    credential: string
  } | null>(null)

  const listQuery = useQuery({
    queryKey: ['devices', { status: statusFilter, doorGroup: doorGroupFilter, offset }],
    queryFn: () =>
      listDevices({
        status: statusFilter || undefined,
        doorGroup: doorGroupFilter.trim() || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    enabled: allowed,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['devices'] })

  function revealCredential(device: DeviceWithCredential) {
    setCredentialReveal({ deviceName: device.name, credential: device.credential })
  }

  const createMutation = useMutation({
    mutationFn: () => createDevice({ name: newName.trim(), door_group: newDoorGroup.trim() }),
    onSuccess: (device) => {
      setNewName('')
      setNewDoorGroup('')
      setShowCreateForm(false)
      invalidate()
      revealCredential(device)
    },
  })

  const editMutation = useMutation({
    mutationFn: () =>
      updateDevice(editTargetId as string, {
        name: editName.trim(),
        door_group: editDoorGroup.trim(),
      }),
    onSuccess: () => {
      setEditTargetId(null)
      invalidate()
    },
  })

  const rotateMutation = useMutation({
    mutationFn: (id: string) => rotateDeviceCredential(id),
    onSuccess: (device) => {
      setRotateTargetId(null)
      invalidate()
      revealCredential(device)
    },
  })

  const disableMutation = useMutation({
    mutationFn: (id: string) => disableDevice(id),
    onSuccess: () => {
      setDisableTargetId(null)
      invalidate()
    },
  })

  if (!allowed) {
    return (
      <>
        <PagePlaceholder
          title="Devices"
          description="Registrasi entry device, status online/offline, dan door group."
        />
        <div className="device-management-denied" role="alert">
          <h2 className="device-management-denied__title">Tidak Ada Akses</h2>
          <p style={{ margin: 0 }}>
            Halaman ini hanya dapat diakses oleh role ADMIN atau OPERATOR. Role kamu saat ini
            {role ? ` (${role})` : ''} tidak memiliki izin untuk melihat data device.
          </p>
        </div>
      </>
    )
  }

  const items = listQuery.data?.items ?? []
  const total = listQuery.data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  const canCreate = canCreateDevice(role)
  const canEdit = canEditDevice(role)
  const canRotate = canRotateDeviceCredential(role)
  const canDisable = canDisableDevice(role)
  const canActivate = canActivateDevice(role)

  const anyMutationPending =
    createMutation.isPending ||
    editMutation.isPending ||
    rotateMutation.isPending ||
    disableMutation.isPending

  function startEdit(device: DeviceResponse) {
    setEditTargetId(device.id)
    setEditName(device.name)
    setEditDoorGroup(device.door_group)
  }

  return (
    <div className="device-management-page">
      <PagePlaceholder
        title="Devices"
        description="Registrasi entry device, status online/offline, dan door group."
      />

      {canCreate && (
        <section
          style={{
            background: 'var(--bg-surface)',
            border: 'var(--border-w) solid var(--border-default)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-sm)',
            padding: 'var(--space-6)',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-3)',
          }}
        >
          {!showCreateForm ? (
            <button
              type="button"
              onClick={() => setShowCreateForm(true)}
              style={{
                alignSelf: 'flex-start',
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--accent)',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                cursor: 'pointer',
              }}
            >
              Tambah Device
            </button>
          ) : (
            <>
              <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Tambah Device Baru</h2>
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  if (newName.trim() && newDoorGroup.trim()) createMutation.mutate()
                }}
                style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}
              >
                <label htmlFor="new-device-name" style={{ display: 'none' }}>
                  Nama Device
                </label>
                <input
                  id="new-device-name"
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                  placeholder="Nama Device (mis. Pintu Lobby)"
                  style={{
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-3)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--border-default)',
                    flex: '1 1 220px',
                  }}
                />
                <label htmlFor="new-device-door-group" style={{ display: 'none' }}>
                  Door Group
                </label>
                <input
                  id="new-device-door-group"
                  value={newDoorGroup}
                  onChange={(event) => setNewDoorGroup(event.target.value)}
                  placeholder="Door Group (mis. lobby)"
                  style={{
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-3)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--border-default)',
                    flex: '1 1 220px',
                  }}
                />
                <button
                  type="submit"
                  disabled={!newName.trim() || !newDoorGroup.trim() || createMutation.isPending}
                  style={{
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-6)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--accent)',
                    background: 'var(--accent)',
                    color: 'var(--text-inverse)',
                    cursor: newName.trim() && newDoorGroup.trim() ? 'pointer' : 'not-allowed',
                    opacity: newName.trim() && newDoorGroup.trim() ? 1 : 0.5,
                  }}
                >
                  {createMutation.isPending ? 'Menyimpan...' : 'Simpan Device'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateForm(false)
                    setNewName('')
                    setNewDoorGroup('')
                  }}
                  style={{
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-4)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--border-strong)',
                    background: 'var(--bg-surface)',
                    cursor: 'pointer',
                  }}
                >
                  Batal
                </button>
              </form>
              {createMutation.isError && (
                <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
                  {describeApiError(createMutation.error)}
                </p>
              )}
            </>
          )}
        </section>
      )}

      <section
        style={{
          background: 'var(--bg-surface)',
          border: 'var(--border-w) solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-sm)',
          padding: 'var(--space-6)',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <form
          onSubmit={(event) => event.preventDefault()}
          style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}
        >
          <label htmlFor="filter-device-status" style={{ display: 'none' }}>
            Filter Status
          </label>
          <select
            id="filter-device-status"
            value={statusFilter}
            onChange={(event) => {
              setOffset(0)
              setStatusFilter(event.target.value as DeviceStatus | '')
            }}
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-3)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              background: 'var(--bg-surface)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="">Semua Status</option>
            {DEVICE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>

          <label htmlFor="filter-door-group" style={{ display: 'none' }}>
            Filter Door Group
          </label>
          <input
            id="filter-door-group"
            value={doorGroupFilter}
            onChange={(event) => {
              setOffset(0)
              setDoorGroupFilter(event.target.value)
            }}
            placeholder="Filter Door Group"
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-3)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
            }}
          />
        </form>

        {listQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
        {listQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(listQuery.error)}
          </p>
        )}

        {(editMutation.isError || rotateMutation.isError || disableMutation.isError) && (
          <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
            {describeApiError(editMutation.error ?? rotateMutation.error ?? disableMutation.error)}
          </p>
        )}

        {!listQuery.isLoading && !listQuery.isError && items.length === 0 && (
          <div className="device-management-empty">
            <h3 className="device-management-empty__title">Belum Ada Device Terdaftar</h3>
            <p className="device-management-empty__hint">
              {statusFilter || doorGroupFilter
                ? 'Tidak ada device yang cocok dengan filter ini.'
                : 'Tambahkan device pertama untuk mulai memantau akses pintu masuk.'}
            </p>
            {canCreate && !statusFilter && !doorGroupFilter && !showCreateForm && (
              <button
                type="button"
                onClick={() => setShowCreateForm(true)}
                style={{
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-6)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--accent)',
                  background: 'var(--accent)',
                  color: 'var(--text-inverse)',
                  cursor: 'pointer',
                }}
              >
                Tambah Device
              </button>
            )}
          </div>
        )}

        {items.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table className="device-table">
              <thead>
                <tr>
                  <th>Nama</th>
                  <th>Door Group</th>
                  <th>Status</th>
                  <th>Heartbeat Terakhir</th>
                  <th>Aksi</th>
                </tr>
              </thead>
              <tbody>
                {items.map((device) => {
                  const isEditing = editTargetId === device.id
                  return (
                    <tr
                      key={device.id}
                      className={isWarningRow(device) ? 'device-table__row--warning' : undefined}
                    >
                      <td>
                        {isEditing ? (
                          <input
                            aria-label={`Nama device ${device.name}`}
                            value={editName}
                            onChange={(event) => setEditName(event.target.value)}
                            style={{
                              minHeight: 'var(--touch-target)',
                              padding: '0 var(--space-2)',
                              borderRadius: 'var(--radius-md)',
                              border: 'var(--border-w) solid var(--border-default)',
                            }}
                          />
                        ) : (
                          device.name
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <input
                            aria-label={`Door group device ${device.name}`}
                            value={editDoorGroup}
                            onChange={(event) => setEditDoorGroup(event.target.value)}
                            style={{
                              minHeight: 'var(--touch-target)',
                              padding: '0 var(--space-2)',
                              borderRadius: 'var(--radius-md)',
                              border: 'var(--border-w) solid var(--border-default)',
                            }}
                          />
                        ) : (
                          device.door_group
                        )}
                      </td>
                      <td>
                        <DeviceStatusBadge status={device.status} isStale={device.is_stale} />
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {formatRelativeTime(device.last_heartbeat_at)}
                      </td>
                      <td>
                        <div className="device-management-actions">
                          {isEditing ? (
                            <>
                              <button
                                type="button"
                                disabled={
                                  !editName.trim() || !editDoorGroup.trim() || anyMutationPending
                                }
                                onClick={() => editMutation.mutate()}
                                style={{
                                  border: 'var(--border-w) solid var(--accent)',
                                  background: 'var(--accent)',
                                  color: 'var(--text-inverse)',
                                }}
                              >
                                {editMutation.isPending ? 'Menyimpan...' : 'Simpan'}
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditTargetId(null)}
                                style={{
                                  border: 'var(--border-w) solid var(--border-strong)',
                                  background: 'var(--bg-surface)',
                                }}
                              >
                                Batal
                              </button>
                            </>
                          ) : (
                            <DeviceActionsMenu
                              device={device}
                              canEdit={canEdit}
                              canRotate={canRotate}
                              canDisable={canDisable}
                              canActivate={canActivate}
                              canEditChecklist={canEdit}
                              anyMutationPending={anyMutationPending}
                              isRotateTarget={rotateTargetId === device.id}
                              isRotatePending={rotateMutation.isPending}
                              isDisableTarget={disableTargetId === device.id}
                              isDisablePending={disableMutation.isPending}
                              onEdit={() => startEdit(device)}
                              onRequestRotate={() => setRotateTargetId(device.id)}
                              onCancelRotate={() => setRotateTargetId(null)}
                              onConfirmRotate={() => rotateMutation.mutate(device.id)}
                              onRequestDisable={() => setDisableTargetId(device.id)}
                              onCancelDisable={() => setDisableTargetId(null)}
                              onConfirmDisable={() => disableMutation.mutate(device.id)}
                              onActivate={() =>
                                setActivateTarget({ id: device.id, name: device.name })
                              }
                              onEditChecklist={() => setChecklistTarget(device)}
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: 'var(--text-muted)', font: 'var(--text-small)' }}>
            {total > 0
              ? `Menampilkan ${offset + 1}-${Math.min(offset + PAGE_SIZE, total)} dari ${total}`
              : null}
          </span>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <button
              type="button"
              disabled={!hasPrev}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-4)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-strong)',
                background: 'var(--bg-surface)',
                opacity: hasPrev ? 1 : 0.5,
                cursor: hasPrev ? 'pointer' : 'not-allowed',
              }}
            >
              Sebelumnya
            </button>
            <button
              type="button"
              disabled={!hasNext}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-4)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-strong)',
                background: 'var(--bg-surface)',
                opacity: hasNext ? 1 : 0.5,
                cursor: hasNext ? 'pointer' : 'not-allowed',
              }}
            >
              Berikutnya
            </button>
          </div>
        </div>
      </section>

      {credentialReveal && (
        <CredentialBootstrapDialog
          deviceName={credentialReveal.deviceName}
          credential={credentialReveal.credential}
          onAcknowledge={() => setCredentialReveal(null)}
        />
      )}

      {activateTarget && (
        <ActivateDeviceDialog
          deviceId={activateTarget.id}
          deviceName={activateTarget.name}
          onClose={() => setActivateTarget(null)}
        />
      )}

      {checklistTarget && (
        <CommissioningChecklistDialog
          device={checklistTarget}
          onClose={() => setChecklistTarget(null)}
          onSaved={() => {
            setChecklistTarget(null)
            invalidate()
          }}
        />
      )}
    </div>
  )
}
