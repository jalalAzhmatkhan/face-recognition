/**
 * Enrollment consent copywriting — the exact text a subject/operator must
 * read before consent can be granted, for the current `CURRENT_CONSENT_VERSION`
 * (`features/enrollment-capture/types.ts`, EC-BE-09's `v1.1`).
 *
 * Shared between `features/enrollment-capture/EnrollmentCapturePage.tsx`
 * (the self-service capture wizard's own consent step) and
 * `pages/EnrollmentDetailPage.tsx` (an operator manually recording consent,
 * e.g. when consent was given verbally rather than through the wizard) so
 * the two paths can never drift out of sync with each other — this is
 * legal/compliance copy, not ordinary UI text, so duplicating it across two
 * files would be a correctness risk, not just a style preference.
 *
 * Bump `CURRENT_CONSENT_VERSION` (and update this text to match) whenever
 * the clauses below change.
 */
export default function EnrollmentConsentCopy() {
  return (
    <>
      <p style={{ font: 'var(--text-consent-body)', color: 'var(--text-secondary)' }}>
        Subjek akan direkam foto wajah dan video orientasi kepala (menoleh dan
        menunduk/mendongak mengikuti pola 12 posisi jam, wajah tetap menghadap
        kamera sepanjang proses) untuk keperluan pendaftaran biometrik. Media
        akan diunggah langsung ke penyimpanan aman dan tidak disimpan pada
        perangkat ini.
      </p>
      <p style={{ font: 'var(--text-consent-body)', color: 'var(--text-secondary)' }}>
        Tampil seperti Anda datang bekerja sehari-hari (hijab, kacamata,
        jenggot seperti biasa boleh dipakai). <strong>Lepaskan masker dan
        kacamata hitam (sunglasses)</strong> selama perekaman — wajah harus
        terlihat jelas dari dagu sampai dahi.
      </p>
      <ul style={{ font: 'var(--text-consent-body)', color: 'var(--text-secondary)' }}>
        <li>
          Sistem akan membuat <strong>template wajah sintetis</strong>{' '}
          (misalnya versi bermasker) secara otomatis dari hasil rekaman ini,
          khusus untuk keperluan pengenalan wajah saat memakai masker.
        </li>
        <li>
          Frame gambar dari <strong>kamera pintu/absensi</strong> saat Anda
          berhasil dikenali sistem dapat dipakai sebagai data kalibrasi
          kualitas pengenalan — bukan disimpan sebagai identitas/enrollment
          baru tanpa kontrol.
        </li>
        <li>
          Data pengenalan sementara (probe) dari beberapa kali Anda berhasil
          dikenali sistem dapat dipakai untuk memperbarui/menyegarkan profil
          wajah Anda secara otomatis, dengan pengaman dan kontrol tertentu.
        </li>
      </ul>
    </>
  )
}
