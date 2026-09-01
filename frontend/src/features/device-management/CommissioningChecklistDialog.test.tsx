import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import CommissioningChecklistDialog from './CommissioningChecklistDialog'
import type { DeviceResponse } from './types'

const { updateDeviceMock, getAccessTokenMock, decodeJwtPayloadMock } = vi.hoisted(() => ({
  updateDeviceMock: vi.fn(),
  getAccessTokenMock: vi.fn(),
  decodeJwtPayloadMock: vi.fn(),
}))

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, updateDevice: updateDeviceMock }
})

vi.mock('../../lib/authToken', async () => {
  const actual = await vi.importActual<typeof import('../../lib/authToken')>('../../lib/authToken')
  return {
    ...actual,
    getAccessToken: getAccessTokenMock,
    decodeJwtPayload: decodeJwtPayloadMock,
  }
})

function device(overrides: Partial<DeviceResponse> = {}): DeviceResponse {
  return {
    id: 'device-1',
    name: 'Panel Absensi Lobi',
    door_group: 'lobby',
    status: 'ONLINE',
    last_heartbeat_at: null,
    credential_rotated_at: null,
    is_stale: false,
    device_class: 'door_entry',
    commissioning_checklist: null,
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

beforeEach(() => {
  getAccessTokenMock.mockReturnValue('fake-token')
  decodeJwtPayloadMock.mockReturnValue({ sub: 'staff-42', role: 'ADMIN' })
  updateDeviceMock.mockResolvedValue(device())
})

describe('CommissioningChecklistDialog', () => {
  it('renders all 13 catalog items grouped by category, queue_zone hidden for door_entry', () => {
    render(<CommissioningChecklistDialog device={device()} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByText('Pemasangan')).toBeInTheDocument()
    expect(screen.getByText('Pencahayaan')).toBeInTheDocument()
    expect(screen.getByText('Setting Kamera')).toBeInTheDocument()
    expect(screen.getByText('Kebijakan Occlusion')).toBeInTheDocument()
    // queue_zone items are all 'na' for door_entry -> section filtered out.
    expect(screen.queryByText('Zona Antrian (Absensi)')).not.toBeInTheDocument()
    expect(screen.getByText('Tinggi kamera dari lantai')).toBeInTheDocument()
  })

  it('shows the queue_zone section and sub-form when device class is attendance', () => {
    render(
      <CommissioningChecklistDialog
        device={device({ device_class: 'attendance' })}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    )
    expect(screen.getByText('Zona Antrian (Absensi)')).toBeInTheDocument()
    expect(screen.getByText('Titik berhenti sudah ditandai')).toBeInTheDocument()
  })

  it('starts with overall_status Pending', () => {
    render(<CommissioningChecklistDialog device={device()} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByTestId('overall-status')).toHaveTextContent('Pending')
  })

  it('auto-suggests pass/fail from measured_value vs expected_range and updates overall_status', async () => {
    render(<CommissioningChecklistDialog device={device()} onClose={vi.fn()} onSaved={vi.fn()} />)
    // mount.camera_height_m expects 1.4-1.7 for door_entry.
    const heightInput = screen.getByPlaceholderText('m')
    fireEvent.change(heightInput, { target: { value: '1.55' } })
    // status should now be 'pass' in the row's status select — find via
    // aria-label pattern "Status <label>"; simplest: overall_status still
    // pending because other required items remain unchecked.
    expect(screen.getByTestId('overall-status')).toHaveTextContent('Pending')

    const outOfRange = screen.getByPlaceholderText('derajat')
    fireEvent.change(outOfRange, { target: { value: '80' } })
    // A single out-of-range required item flips overall_status straight to
    // Failed (fail takes priority over pending in computeOverallStatus),
    // even though other required items are still unchecked.
    await waitFor(() => expect(screen.getByTestId('overall-status')).toHaveTextContent('Failed'))
  })

  it('submits PATCH /devices/{id} with device_class + commissioning_checklist matching the §5 shape', async () => {
    const onSaved = vi.fn()
    render(<CommissioningChecklistDialog device={device()} onClose={vi.fn()} onSaved={onSaved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Simpan Checklist' }))

    await waitFor(() => expect(updateDeviceMock).toHaveBeenCalledTimes(1))
    const [id, body] = updateDeviceMock.mock.calls[0]
    expect(id).toBe('device-1')
    expect(body.device_class).toBe('door_entry')
    expect(body.commissioning_checklist.schema_version).toBe('1.0')
    expect(body.commissioning_checklist.checks).toHaveLength(13)
    expect(body.commissioning_checklist.overall_status).toBe('pending')
    expect(body.commissioning_checklist.queue_zone).toBeNull()
    expect(onSaved).toHaveBeenCalled()
  })

  it('stamps commissioned_by_staff_id/commissioned_at only once overall_status leaves pending', async () => {
    const existing = device({
      device_class: 'door_entry',
      commissioning_checklist: {
        schema_version: '1.0',
        device_class: 'door_entry',
        overall_status: 'pending',
        commissioned_at: null,
        commissioned_by_staff_id: null,
        commissioned_by_name: null,
        site_notes: null,
        queue_zone: null,
        checks: [
          {
            id: 'mount.camera_height_m',
            category: 'mounting',
            label: 'Tinggi kamera dari lantai',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'number',
            unit: 'm',
            expected_range: { min: 1.4, max: 1.7 },
            measured_value: 1.5,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'mount.pitch_degrees',
            category: 'mounting',
            label: 'Sudut pitch kamera',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'number',
            unit: 'derajat',
            expected_range: { min: -15, max: 15 },
            measured_value: 2,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'mount.mount_type',
            category: 'mounting',
            label: 'Jenis pemasangan',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'enum',
            enum_options: ['wall_mount', 'pole_mount', 'panel_integrated', 'ceiling_mount'],
            measured_value: 'wall_mount',
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'mount.no_ceiling_downward',
            category: 'mounting',
            label: 'Bukan ceiling-mount menghadap ke bawah',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: true,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'lighting.fill_light_installed',
            category: 'lighting',
            label: 'Fill-light terpasang & menyala',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: true,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'lighting.backlight_avoided',
            category: 'lighting',
            label: 'x',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: true,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'camera_settings.wdr_hdr_enabled',
            category: 'camera_settings',
            label: 'x',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: true,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'camera_settings.ae_lock_face',
            category: 'camera_settings',
            label: 'x',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: true,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'camera_settings.shutter_speed',
            category: 'camera_settings',
            label: 'x',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: true,
            value_type: 'number',
            unit: '1/detik (penyebut)',
            expected_range: { min: 250, max: 4000 },
            measured_value: 500,
            status: 'pass',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'occlusion_policy.helmet_removal_signage',
            category: 'occlusion_policy',
            label: 'x',
            applicable_device_classes: ['door_entry', 'attendance'],
            required: false,
            value_type: 'boolean',
            expected_value: true,
            measured_value: null,
            status: null,
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'queue_zone.stop_point_defined',
            category: 'queue_zone',
            label: 'x',
            applicable_device_classes: ['attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: null,
            status: 'na',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'queue_zone.single_face_zone_defined',
            category: 'queue_zone',
            label: 'x',
            applicable_device_classes: ['attendance'],
            required: true,
            value_type: 'boolean',
            expected_value: true,
            measured_value: null,
            status: 'na',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
          {
            id: 'queue_zone.zone_reference_photo_uploaded',
            category: 'queue_zone',
            label: 'x',
            applicable_device_classes: ['attendance'],
            required: true,
            value_type: 'photo_ref',
            measured_value: null,
            status: 'na',
            notes: null,
            checked_at: null,
            checked_by_staff_id: null,
          },
        ],
        reverify_due_at: null,
      },
    })

    render(<CommissioningChecklistDialog device={existing} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByTestId('overall-status')).toHaveTextContent('Passed')

    fireEvent.click(screen.getByRole('button', { name: 'Simpan Checklist' }))
    await waitFor(() => expect(updateDeviceMock).toHaveBeenCalledTimes(1))
    const [, body] = updateDeviceMock.mock.calls[0]
    expect(body.commissioning_checklist.overall_status).toBe('passed')
    expect(body.commissioning_checklist.commissioned_by_staff_id).toBe('staff-42')
    expect(body.commissioning_checklist.commissioned_at).not.toBeNull()
  })

  it('shows an error message when the save fails', async () => {
    updateDeviceMock.mockRejectedValue(new Error('network down'))
    render(<CommissioningChecklistDialog device={device()} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Simpan Checklist' }))
    expect(await screen.findByText('network down')).toBeInTheDocument()
  })

  it('calls onClose when Batal is clicked', () => {
    const onClose = vi.fn()
    render(<CommissioningChecklistDialog device={device()} onClose={onClose} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Batal' }))
    expect(onClose).toHaveBeenCalled()
  })
})
