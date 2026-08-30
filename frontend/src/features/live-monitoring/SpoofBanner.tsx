/** Banner alert shown while there's at least one unreviewed
 * SPOOF_SUSPECTED event in the feed (screen-plan S-40 + NFR-SEC-06:
 * "Event spoof-suspected: ... banner alert atas"). The per-event "tandai
 * ditinjau" action lives on `AccessEventItem`; this banner just surfaces
 * the aggregate count so it can't be missed if the operator has scrolled
 * away from the item itself. */
export default function SpoofBanner({ unreviewedCount }: { unreviewedCount: number }) {
  if (unreviewedCount === 0) return null
  return (
    <div className="alert-banner alert-banner--danger" role="alert" data-testid="spoof-banner">
      <strong>
        {unreviewedCount} event dicurigai spoof belum ditinjau.
      </strong>{' '}
      Periksa item bertanda "Dicurigai spoof" di feed dan tandai setelah ditinjau.
    </div>
  )
}
