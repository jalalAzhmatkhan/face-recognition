import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import PromoteConfirmDialog from './PromoteConfirmDialog'

afterEach(() => cleanup())

/** Credential-dialog-like confirmation: the underlying action
 * (`POST /models/{version}/promote`) is irreversible-ish, so this dialog
 * must never let `onConfirm` fire from just opening the dialog or clicking
 * around — only after the explicit acknowledge checkbox is ticked AND the
 * confirm button is clicked. */
describe('PromoteConfirmDialog', () => {
  it('disables the confirm button until the acknowledge checkbox is checked, and never calls onConfirm on its own', () => {
    const onConfirm = vi.fn()
    render(
      <PromoteConfirmDialog
        candidateVersion="facenet-v2"
        productionVersion="facenet-v1"
        isSubmitting={false}
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    )

    const confirmButton = screen.getByRole('button', { name: 'Promote ke Produksi' })
    expect(confirmButton).toBeDisabled()
    expect(onConfirm).not.toHaveBeenCalled()

    fireEvent.click(confirmButton)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('enables the confirm button only after the checkbox is ticked, and calls onConfirm exactly once when clicked', () => {
    const onConfirm = vi.fn()
    render(
      <PromoteConfirmDialog
        candidateVersion="facenet-v2"
        productionVersion="facenet-v1"
        isSubmitting={false}
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('checkbox'))
    const confirmButton = screen.getByRole('button', { name: 'Promote ke Produksi' })
    expect(confirmButton).toBeEnabled()

    fireEvent.click(confirmButton)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('mentions that gallery re-embedding (TR-08) is not automatic', () => {
    render(
      <PromoteConfirmDialog
        candidateVersion="facenet-v2"
        productionVersion={null}
        isSubmitting={false}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByText(/re-embedding gallery.*belum otomatis/i)).toBeInTheDocument()
    expect(screen.getByText(/promosi pertama/i)).toBeInTheDocument()
  })
})
