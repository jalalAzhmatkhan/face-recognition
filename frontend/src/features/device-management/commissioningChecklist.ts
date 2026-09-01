import type {
  ChecklistItem,
  ChecklistOverallStatus,
  CommissioningChecklist,
  DeviceClass,
  QueueZone,
} from './types'

/** Both real device classes — the checklist item catalog only ever cares
 * about the two real classes, never `unknown` (a device must be classified
 * as `door_entry` or `attendance` before commissioning makes sense; see
 * `CommissioningChecklistDialog.tsx`). */
const BOTH_CLASSES: DeviceClass[] = ['door_entry', 'attendance']
const ATTENDANCE_ONLY: DeviceClass[] = ['attendance']

/** Static field set for one catalog entry (the parts that never change per
 * device) — `buildDefaultChecklist` below fills in the per-instance fields
 * (`measured_value`, `status`, `notes`, `checked_at`, `checked_by_staff_id`)
 * plus the one field whose *value* legitimately varies by device class
 * (`mount.camera_height_m`'s `expected_range`, per camera-placement-guide.md
 * §1.2). */
type CatalogEntry = Omit<
  ChecklistItem,
  'measured_value' | 'status' | 'notes' | 'checked_at' | 'checked_by_staff_id'
>

/**
 * The 13 baseline checklist items (camera-placement-guide.md §5.4),
 * rendered in this exact order, grouped by `category` for the form UI.
 * `id`/`category`/`label`/`value_type`/`enum_options`/`applicable_device_classes`
 * are copied verbatim from §5.4's table.
 */
export function buildChecklistCatalog(deviceClass: DeviceClass): CatalogEntry[] {
  return [
    {
      id: 'mount.camera_height_m',
      category: 'mounting',
      label: 'Tinggi kamera dari lantai',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'number',
      unit: 'm',
      // §1.2: attendance is stricter (1.5-1.6m) than door_entry (1.4-1.7m).
      expected_range: deviceClass === 'attendance' ? { min: 1.5, max: 1.6 } : { min: 1.4, max: 1.7 },
    },
    {
      id: 'mount.pitch_degrees',
      category: 'mounting',
      label: 'Sudut pitch kamera',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'number',
      unit: 'derajat',
      expected_range: { min: -15, max: 15 },
    },
    {
      id: 'mount.mount_type',
      category: 'mounting',
      label: 'Jenis pemasangan',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'enum',
      enum_options: ['wall_mount', 'pole_mount', 'panel_integrated', 'ceiling_mount'],
    },
    {
      id: 'mount.no_ceiling_downward',
      category: 'mounting',
      label: 'Bukan ceiling-mount menghadap ke bawah',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'lighting.fill_light_installed',
      category: 'lighting',
      label: 'Fill-light terpasang & menyala',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'lighting.backlight_avoided',
      category: 'lighting',
      label: 'Tidak ada sumber cahaya kuat di belakang subjek (dicek pagi & sore)',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'camera_settings.wdr_hdr_enabled',
      category: 'camera_settings',
      label: 'WDR/HDR aktif',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'camera_settings.ae_lock_face',
      category: 'camera_settings',
      label: 'AE-lock/metering area wajah aktif (bukan global)',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'camera_settings.shutter_speed',
      category: 'camera_settings',
      label: 'Shutter speed minimum',
      applicable_device_classes: BOTH_CLASSES,
      required: true,
      value_type: 'number',
      unit: '1/detik (penyebut)',
      expected_range: { min: 250, max: 4000 },
    },
    {
      id: 'occlusion_policy.helmet_removal_signage',
      category: 'occlusion_policy',
      label: 'Signage kebijakan lepas helm terpasang',
      applicable_device_classes: BOTH_CLASSES,
      required: false,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'queue_zone.stop_point_defined',
      category: 'queue_zone',
      label: 'Titik berhenti ditandai (bukan koridor)',
      applicable_device_classes: ATTENDANCE_ONLY,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'queue_zone.single_face_zone_defined',
      category: 'queue_zone',
      label: 'Zona satu-wajah digambar & dikonfirmasi',
      applicable_device_classes: ATTENDANCE_ONLY,
      required: true,
      value_type: 'boolean',
      expected_value: true,
    },
    {
      id: 'queue_zone.zone_reference_photo_uploaded',
      category: 'queue_zone',
      label: 'Foto referensi zona sudah diunggah ke S3',
      applicable_device_classes: ATTENDANCE_ONLY,
      required: true,
      value_type: 'photo_ref',
    },
  ]
}

/** `na` for an item not applicable to `deviceClass`, otherwise "not yet
 * checked" (`null`) — matches camera-placement-guide.md §5.2's `status`
 * semantics ("na" = tidak berlaku, auto-follows `applicable_device_classes`). */
function initialStatusFor(entry: CatalogEntry, deviceClass: DeviceClass): ChecklistItem['status'] {
  return entry.applicable_device_classes.includes(deviceClass) ? null : 'na'
}

export function buildDefaultQueueZone(): QueueZone {
  return {
    stop_point_marked: false,
    stop_point_distance_m: null,
    single_face_zone_defined: false,
    zone_shape: null,
    zone_reference_photo_s3_key: null,
    notes: null,
  }
}

/** Builds a fresh, all-unchecked checklist for `deviceClass` — used when a
 * device has no `commissioning_checklist` yet (`null`) or when its
 * `schema_version` isn't the one this form understands. */
export function buildDefaultChecklist(deviceClass: DeviceClass): CommissioningChecklist {
  const catalog = buildChecklistCatalog(deviceClass)
  return {
    schema_version: '1.0',
    device_class: deviceClass,
    overall_status: 'pending',
    commissioned_at: null,
    commissioned_by_staff_id: null,
    commissioned_by_name: null,
    site_notes: null,
    checks: catalog.map((entry) => ({
      ...entry,
      measured_value: null,
      status: initialStatusFor(entry, deviceClass),
      notes: null,
      checked_at: null,
      checked_by_staff_id: null,
    })),
    queue_zone: deviceClass === 'attendance' ? buildDefaultQueueZone() : null,
  }
}

/**
 * Re-derives each item's applicability (and the `na` shortcut for
 * inapplicable ones) after the operator changes the device class mid-form,
 * WITHOUT discarding any `measured_value`/`notes` already entered — only
 * `status` is adjusted: inapplicable → `na`, applicable-but-was-`na` →
 * reset to `null` (not yet checked) so it isn't silently counted as
 * checked. Also toggles `queue_zone` on/off (built fresh, or dropped to
 * `null` for a non-attendance class per §5.1: "null untuk door_entry").
 */
export function reclassifyChecklist(
  checklist: CommissioningChecklist,
  deviceClass: DeviceClass,
): CommissioningChecklist {
  return {
    ...checklist,
    device_class: deviceClass,
    checks: checklist.checks.map((item) => {
      const applicable = item.applicable_device_classes.includes(deviceClass)
      if (!applicable) return { ...item, status: 'na' }
      if (item.status === 'na') return { ...item, status: null }
      return item
    }),
    queue_zone:
      deviceClass === 'attendance' ? (checklist.queue_zone ?? buildDefaultQueueZone()) : null,
  }
}

/**
 * `overall_status` per camera-placement-guide.md §5.1: computed from every
 * `required: true` item that is ALSO applicable to `deviceClass` (an
 * inapplicable required item is `na`, never part of this aggregation).
 * `failed` if any such item is `fail`; `pending` if any is still
 * unchecked (`null`); otherwise `passed`.
 */
export function computeOverallStatus(
  checks: ChecklistItem[],
  deviceClass: DeviceClass,
): ChecklistOverallStatus {
  const effective = checks.filter(
    (item) => item.required && item.applicable_device_classes.includes(deviceClass),
  )
  if (effective.some((item) => item.status === 'fail')) return 'failed'
  if (effective.some((item) => item.status === null)) return 'pending'
  return 'passed'
}
