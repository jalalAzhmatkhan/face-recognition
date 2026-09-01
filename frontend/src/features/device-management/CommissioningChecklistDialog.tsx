import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import {
  buildDefaultChecklist,
  computeOverallStatus,
  reclassifyChecklist,
} from './commissioningChecklist'
import { describeApiError, updateDevice } from './api'
import { decodeJwtPayload, getAccessToken } from '../../lib/authToken'
import { DEVICE_CLASSES } from './types'
import type {
  ChecklistItem,
  ChecklistItemStatus,
  CommissioningChecklist,
  DeviceClass,
  DeviceResponse,
  QueueZone,
} from './types'

const CATEGORY_LABELS: Record<ChecklistItem['category'], string> = {
  mounting: 'Pemasangan',
  lighting: 'Pencahayaan',
  camera_settings: 'Setting Kamera',
  occlusion_policy: 'Kebijakan Occlusion',
  queue_zone: 'Zona Antrian (Absensi)',
}

const CATEGORY_ORDER: ChecklistItem['category'][] = [
  'mounting',
  'lighting',
  'camera_settings',
  'occlusion_policy',
  'queue_zone',
]

const DEVICE_CLASS_LABELS: Record<DeviceClass, string> = {
  door_entry: 'Pintu Akses (access_control)',
  attendance: 'Absensi (attendance)',
  unknown: 'Belum Diklasifikasi',
}

const STATUS_LABELS: Record<Exclude<ChecklistItemStatus, null>, string> = {
  pass: 'Pass',
  fail: 'Fail',
  na: 'N/A',
}

/** `sub` claim of the current staff JWT (backend-issued UUID) — used to
 * stamp `checked_by_staff_id`/`commissioned_by_staff_id` per
 * camera-placement-guide.md §5.2/§5.1, mirroring the read-only pattern
 * `lib/authToken.ts::getCurrentRole` already uses for the `role` claim. */
function getCurrentStaffId(): string | null {
  const token = getAccessToken()
  if (!token) return null
  const payload = decodeJwtPayload(token)
  return typeof payload?.sub === 'string' ? payload.sub : null
}

function inputStyle(): CSSProperties {
  return {
    minHeight: 'var(--touch-target)',
    padding: '0 var(--space-2)',
    borderRadius: 'var(--radius-md)',
    border: 'var(--border-w) solid var(--border-default)',
    background: 'var(--bg-surface)',
    color: 'var(--text-primary)',
  }
}

/** Auto-suggests a status from `measured_value` vs. `expected_range`/
 * `expected_value` when the value type supports it (number/boolean) —
 * enum/text/photo_ref items have no single "correct" value defined by the
 * catalog, so those stay whatever the operator picks manually. */
function suggestStatus(item: ChecklistItem): ChecklistItemStatus {
  if (item.measured_value === null || item.measured_value === '') return null
  if (item.value_type === 'number' && item.expected_range) {
    const value = Number(item.measured_value)
    if (Number.isNaN(value)) return null
    return value >= item.expected_range.min && value <= item.expected_range.max ? 'pass' : 'fail'
  }
  if (item.value_type === 'boolean' && typeof item.expected_value === 'boolean') {
    return item.measured_value === item.expected_value ? 'pass' : 'fail'
  }
  return item.status
}

function ChecklistItemRow({
  item,
  onChange,
}: {
  item: ChecklistItem
  onChange: (next: ChecklistItem) => void
}) {
  const isNa = item.status === 'na'

  function updateMeasuredValue(value: ChecklistItem['measured_value']) {
    const next = { ...item, measured_value: value, checked_at: new Date().toISOString() }
    onChange({ ...next, status: suggestStatus(next) })
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        padding: 'var(--space-3)',
        borderRadius: 'var(--radius-md)',
        border: 'var(--border-w) solid var(--border-default)',
        opacity: isNa ? 0.55 : 1,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)' }}>
        <label
          htmlFor={`check-${item.id}`}
          style={{ font: 'var(--text-small)', fontWeight: 600, color: 'var(--text-primary)' }}
        >
          {item.label}
          {item.required && <span style={{ color: 'var(--danger)' }}> *</span>}
        </label>
        {isNa && (
          <span style={{ font: 'var(--text-caption)', color: 'var(--text-muted)' }}>
            Tidak berlaku untuk device class ini
          </span>
        )}
      </div>

      {!isNa && (
        <>
          <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            {item.value_type === 'number' && (
              <input
                id={`check-${item.id}`}
                type="number"
                value={typeof item.measured_value === 'number' ? item.measured_value : ''}
                onChange={(e) =>
                  updateMeasuredValue(e.target.value === '' ? null : Number(e.target.value))
                }
                placeholder={item.unit ?? undefined}
                style={{ ...inputStyle(), flex: '1 1 160px' }}
              />
            )}
            {item.value_type === 'boolean' && (
              <select
                id={`check-${item.id}`}
                value={
                  item.measured_value === null ? '' : item.measured_value ? 'true' : 'false'
                }
                onChange={(e) =>
                  updateMeasuredValue(e.target.value === '' ? null : e.target.value === 'true')
                }
                style={{ ...inputStyle(), flex: '1 1 160px' }}
              >
                <option value="">Belum diisi</option>
                <option value="true">Ya</option>
                <option value="false">Tidak</option>
              </select>
            )}
            {item.value_type === 'enum' && (
              <select
                id={`check-${item.id}`}
                value={typeof item.measured_value === 'string' ? item.measured_value : ''}
                onChange={(e) => updateMeasuredValue(e.target.value === '' ? null : e.target.value)}
                style={{ ...inputStyle(), flex: '1 1 200px' }}
              >
                <option value="">Pilih...</option>
                {(item.enum_options ?? []).map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            )}
            {(item.value_type === 'text' || item.value_type === 'photo_ref') && (
              <input
                id={`check-${item.id}`}
                type="text"
                value={typeof item.measured_value === 'string' ? item.measured_value : ''}
                onChange={(e) => updateMeasuredValue(e.target.value === '' ? null : e.target.value)}
                placeholder={
                  item.value_type === 'photo_ref' ? 'S3 object key (mis. media/devices/...)' : undefined
                }
                style={{ ...inputStyle(), flex: '1 1 260px', fontFamily: 'var(--font-mono)' }}
              />
            )}

            <label htmlFor={`status-${item.id}`} style={{ display: 'none' }}>
              Status {item.label}
            </label>
            <select
              id={`status-${item.id}`}
              value={item.status ?? ''}
              onChange={(e) =>
                onChange({
                  ...item,
                  status: (e.target.value || null) as ChecklistItemStatus,
                })
              }
              style={{ ...inputStyle(), flex: '0 1 120px' }}
            >
              <option value="">Belum dicek</option>
              <option value="pass">{STATUS_LABELS.pass}</option>
              <option value="fail">{STATUS_LABELS.fail}</option>
              <option value="na">{STATUS_LABELS.na}</option>
            </select>
          </div>

          {item.expected_range && (
            <p style={{ margin: 0, font: 'var(--text-caption)', color: 'var(--text-muted)' }}>
              Rentang wajar: {item.expected_range.min} – {item.expected_range.max}
              {item.unit ? ` ${item.unit}` : ''}
            </p>
          )}

          <label htmlFor={`notes-${item.id}`} style={{ display: 'none' }}>
            Catatan {item.label}
          </label>
          <input
            id={`notes-${item.id}`}
            type="text"
            value={item.notes ?? ''}
            onChange={(e) => onChange({ ...item, notes: e.target.value || null })}
            placeholder="Catatan (opsional)"
            style={inputStyle()}
          />
        </>
      )}
    </div>
  )
}

function QueueZoneSection({
  queueZone,
  onChange,
}: {
  queueZone: QueueZone
  onChange: (next: QueueZone) => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <input
            type="checkbox"
            checked={queueZone.stop_point_marked}
            onChange={(e) => onChange({ ...queueZone, stop_point_marked: e.target.checked })}
          />
          Titik berhenti sudah ditandai
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <input
            type="checkbox"
            checked={queueZone.single_face_zone_defined}
            onChange={(e) =>
              onChange({ ...queueZone, single_face_zone_defined: e.target.checked })
            }
          />
          Zona satu-wajah sudah digambar
        </label>
      </div>

      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <label htmlFor="queue-zone-distance" style={{ display: 'none' }}>
          Jarak titik berhenti (m)
        </label>
        <input
          id="queue-zone-distance"
          type="number"
          value={queueZone.stop_point_distance_m ?? ''}
          onChange={(e) =>
            onChange({
              ...queueZone,
              stop_point_distance_m: e.target.value === '' ? null : Number(e.target.value),
            })
          }
          placeholder="Jarak titik berhenti (m)"
          style={{ ...inputStyle(), flex: '1 1 200px' }}
        />

        <label htmlFor="queue-zone-shape" style={{ display: 'none' }}>
          Bentuk zona
        </label>
        <select
          id="queue-zone-shape"
          value={queueZone.zone_shape ?? ''}
          onChange={(e) =>
            onChange({
              ...queueZone,
              zone_shape: (e.target.value || null) as QueueZone['zone_shape'],
            })
          }
          style={{ ...inputStyle(), flex: '1 1 160px' }}
        >
          <option value="">Bentuk zona...</option>
          <option value="box">box</option>
          <option value="circle">circle</option>
          <option value="polygon">polygon</option>
        </select>

        <label htmlFor="queue-zone-photo" style={{ display: 'none' }}>
          S3 key foto referensi zona
        </label>
        <input
          id="queue-zone-photo"
          type="text"
          value={queueZone.zone_reference_photo_s3_key ?? ''}
          onChange={(e) =>
            onChange({ ...queueZone, zone_reference_photo_s3_key: e.target.value || null })
          }
          placeholder="S3 key foto referensi zona"
          style={{ ...inputStyle(), flex: '1 1 260px', fontFamily: 'var(--font-mono)' }}
        />
      </div>

      <label htmlFor="queue-zone-notes" style={{ display: 'none' }}>
        Catatan zona antrian
      </label>
      <input
        id="queue-zone-notes"
        type="text"
        value={queueZone.notes ?? ''}
        onChange={(e) => onChange({ ...queueZone, notes: e.target.value || null })}
        placeholder="Catatan zona (opsional)"
        style={inputStyle()}
      />
    </div>
  )
}

/**
 * EC-FE-01 — commissioning checklist form (S-60 Device Management),
 * rendering the 13 baseline items from
 * `documentation/operations/camera-placement-guide.md` §5.4, grouped by
 * category, plus the `queue_zone` sub-form for `attendance` devices (§5.3).
 * Saves via `PATCH /devices/{id}` with `device_class` +
 * `commissioning_checklist` (BE-09/EC-BE-01 contract) — the backend does
 * NOT validate this JSON structurally (still `dict[str, Any]`, see
 * `backend/app/schemas/devices.py`), so this form is the only place
 * enforcing the §5 contract for Gelombang 0.
 *
 * `photo_ref` items (`queue_zone.zone_reference_photo_uploaded` here, and
 * `queue_zone.zone_reference_photo_s3_key` in the queue-zone sub-form) are
 * plain text inputs for the S3 object key — a full presigned-URL upload
 * widget is a separate scope (task instructions, Gelombang 0 limitation).
 */
export default function CommissioningChecklistDialog({
  device,
  onClose,
  onSaved,
}: {
  device: DeviceResponse
  onClose: () => void
  onSaved: () => void
}) {
  const initialDeviceClass: DeviceClass =
    device.device_class && device.device_class !== 'unknown' ? device.device_class : 'door_entry'

  const [deviceClass, setDeviceClass] = useState<DeviceClass>(initialDeviceClass)
  const [checklist, setChecklist] = useState<CommissioningChecklist>(() =>
    device.commissioning_checklist && device.commissioning_checklist.schema_version === '1.0'
      ? device.commissioning_checklist
      : buildDefaultChecklist(initialDeviceClass),
  )
  const [siteNotes, setSiteNotes] = useState(checklist.site_notes ?? '')
  const [commissionedByName, setCommissionedByName] = useState(checklist.commissioned_by_name ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function handleDeviceClassChange(next: DeviceClass) {
    setDeviceClass(next)
    setChecklist((current) => reclassifyChecklist(current, next))
  }

  function updateItem(next: ChecklistItem) {
    setChecklist((current) => ({
      ...current,
      checks: current.checks.map((item) => (item.id === next.id ? next : item)),
    }))
  }

  const overallStatus = computeOverallStatus(checklist.checks, deviceClass)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setIsSaving(true)
    setSaveError(null)
    try {
      const staffId = getCurrentStaffId()
      const now = new Date().toISOString()
      const finalChecklist: CommissioningChecklist = {
        ...checklist,
        device_class: deviceClass,
        overall_status: overallStatus,
        site_notes: siteNotes || null,
        commissioned_by_name: commissionedByName || null,
        commissioned_by_staff_id: overallStatus !== 'pending' ? staffId : checklist.commissioned_by_staff_id,
        commissioned_at: overallStatus !== 'pending' ? now : checklist.commissioned_at,
      }
      await updateDevice(device.id, {
        device_class: deviceClass,
        commissioning_checklist: finalChecklist,
      })
      onSaved()
    } catch (error) {
      setSaveError(describeApiError(error))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div
      role="presentation"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        padding: 'var(--space-4)',
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="commissioning-checklist-title"
        style={{
          background: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-md)',
          padding: 'var(--space-6)',
          maxWidth: 720,
          width: '100%',
          maxHeight: '90vh',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <h2 id="commissioning-checklist-title" style={{ margin: 0, font: 'var(--text-h3)' }}>
          Checklist Komisioning: {device.name}
        </h2>
        <p style={{ margin: 0, color: 'var(--text-secondary)', font: 'var(--text-small)' }}>
          Diisi saat instalasi/komisioning fisik kamera di lokasi (
          documentation/operations/camera-placement-guide.md §5). Item bertanda{' '}
          <span style={{ color: 'var(--danger)' }}>*</span> wajib untuk menentukan status akhir.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
          <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}>
            <label htmlFor="checklist-device-class" style={{ font: 'var(--text-small)', fontWeight: 600 }}>
              Device Class
            </label>
            <select
              id="checklist-device-class"
              value={deviceClass}
              onChange={(e) => handleDeviceClassChange(e.target.value as DeviceClass)}
              style={{ ...inputStyle(), flex: '1 1 220px' }}
            >
              {DEVICE_CLASSES.filter((c) => c !== 'unknown').map((c) => (
                <option key={c} value={c}>
                  {DEVICE_CLASS_LABELS[c]}
                </option>
              ))}
            </select>

            <span
              data-testid="overall-status"
              style={{
                font: 'var(--text-small)',
                fontWeight: 600,
                padding: '2px var(--space-3)',
                borderRadius: 'var(--radius-full)',
                color: 'var(--text-inverse)',
                background:
                  overallStatus === 'passed'
                    ? 'var(--success)'
                    : overallStatus === 'failed'
                      ? 'var(--danger)'
                      : 'var(--warning)',
              }}
            >
              Status: {overallStatus === 'passed' ? 'Passed' : overallStatus === 'failed' ? 'Failed' : 'Pending'}
            </span>
          </div>

          {CATEGORY_ORDER.filter(
            (category) =>
              category !== 'queue_zone' ||
              checklist.checks.some((c) => c.category === 'queue_zone' && c.status !== 'na'),
          ).map((category) => (
            <fieldset
              key={category}
              style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', border: 'none', margin: 0, padding: 0 }}
            >
              <legend style={{ font: 'var(--text-small)', fontWeight: 700, color: 'var(--text-secondary)' }}>
                {CATEGORY_LABELS[category]}
              </legend>
              {checklist.checks
                .filter((item) => item.category === category)
                .map((item) => (
                  <ChecklistItemRow key={item.id} item={item} onChange={updateItem} />
                ))}
              {category === 'queue_zone' && checklist.queue_zone && (
                <QueueZoneSection
                  queueZone={checklist.queue_zone}
                  onChange={(next) => setChecklist((current) => ({ ...current, queue_zone: next }))}
                />
              )}
            </fieldset>
          ))}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            <label htmlFor="commissioned-by-name" style={{ font: 'var(--text-small)', fontWeight: 600 }}>
              Nama Staff yang Mengomisioning
            </label>
            <input
              id="commissioned-by-name"
              type="text"
              value={commissionedByName}
              onChange={(e) => setCommissionedByName(e.target.value)}
              placeholder="Nama staff lapangan"
              style={inputStyle()}
            />

            <label htmlFor="site-notes" style={{ font: 'var(--text-small)', fontWeight: 600 }}>
              Catatan Lokasi
            </label>
            <input
              id="site-notes"
              type="text"
              value={siteNotes}
              onChange={(e) => setSiteNotes(e.target.value)}
              placeholder="Catatan bebas (opsional)"
              style={inputStyle()}
            />
          </div>

          {saveError && (
            <p role="alert" style={{ margin: 0, color: 'var(--danger)', font: 'var(--text-small)' }}>
              {saveError}
            </p>
          )}

          <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
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
            <button
              type="submit"
              disabled={isSaving}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--accent)',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                cursor: isSaving ? 'not-allowed' : 'pointer',
                opacity: isSaving ? 0.6 : 1,
              }}
            >
              {isSaving ? 'Menyimpan...' : 'Simpan Checklist'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
