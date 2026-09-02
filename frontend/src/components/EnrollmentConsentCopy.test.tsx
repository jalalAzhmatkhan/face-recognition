import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import EnrollmentConsentCopy from './EnrollmentConsentCopy'
import { CURRENT_CONSENT_VERSION } from '../features/enrollment-capture/types'

afterEach(() => cleanup())

/**
 * This is legal/compliance copy, not ordinary UI text: it states what the
 * subject is agreeing to have recorded. When the capture changed from a
 * video sweep to per-position photos (FR-ENR-02), leaving the old wording
 * in place would have meant collecting consent for a recording that no
 * longer happens — which is not informed consent. These tests pin the
 * described capture to the capture that actually runs.
 */
describe('EnrollmentConsentCopy', () => {
  it('describes the capture as photos, and says outright that nothing is recorded as video', () => {
    render(<EnrollmentConsentCopy />)

    expect(screen.getByText(/difoto/)).toBeInTheDocument()
    expect(screen.getByText(/Tidak ada video yang direkam/)).toBeInTheDocument()
  })

  it('never promises a video recording anywhere in the consent text', () => {
    const { container } = render(<EnrollmentConsentCopy />)
    const text = container.textContent ?? ''

    // The only permitted mention is the explicit disclaimer above.
    const videoMentions = text.match(/video/gi) ?? []
    expect(videoMentions).toHaveLength(1)
    expect(text).toContain('Tidak ada video yang direkam')
  })

  it('tells the subject the photos are taken automatically per clock position', () => {
    const { container } = render(<EnrollmentConsentCopy />)
    const text = container.textContent ?? ''

    expect(text).toMatch(/diambil otomatis/)
    expect(text).toMatch(/12 posisi jam/)
  })

  it('still carries the three ASM-EC-05 clauses', () => {
    render(<EnrollmentConsentCopy />)

    expect(screen.getByText(/template wajah sintetis/)).toBeInTheDocument()
    expect(screen.getByText(/kamera pintu\/absensi/)).toBeInTheDocument()
    expect(
      screen.getByText(/memperbarui\/menyegarkan profil wajah Anda secara/),
    ).toBeInTheDocument()
  })

  it('still requires masks and sunglasses to be removed', () => {
    render(<EnrollmentConsentCopy />)

    expect(screen.getByText(/Lepaskan masker dan/)).toBeInTheDocument()
  })

  it('is at a consent version later than the video-era v1.1', () => {
    // The copy above and CURRENT_CONSENT_VERSION must move together: a
    // changed description of what is recorded is a new consent, and grants
    // are stored against the version string, not the text.
    expect(CURRENT_CONSENT_VERSION).toBe('v1.2')
  })
})
