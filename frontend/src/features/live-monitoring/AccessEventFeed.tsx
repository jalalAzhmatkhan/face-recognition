import { useMemo, useRef, useState } from 'react'
import AccessEventItem from './AccessEventItem'
import type { AccessEventPayload } from './types'

interface AccessEventFeedProps {
  events: AccessEventPayload[]
  deviceNames: Map<string, string>
  isLoading: boolean
  reviewedSpoofIds: Set<string>
  onMarkReviewed: (id: string) => void
  /** ids that arrived within this render pass — drives the slide-in
   * animation on `AccessEventItem`. */
  newIds: Set<string>
  /** FE-10: opens the S-41 detail drawer for the clicked row. */
  onSelectEvent: (event: AccessEventPayload) => void
}

const SCROLL_TOP_THRESHOLD_PX = 24

/**
 * Main live-feed list (screen-plan S-40). Handles:
 *  - loading skeleton (before the first snapshot/event arrives)
 *  - empty state ("Belum ada aktivitas")
 *  - "scroll-pinning saat operator membaca": once the operator scrolls
 *    away from the top, new events are held back behind a "N event baru"
 *    pill instead of shoving the list they're reading down. Scrolling back
 *    to the top (or clicking the pill) resumes live updates.
 */
export default function AccessEventFeed({
  events,
  deviceNames,
  isLoading,
  reviewedSpoofIds,
  onMarkReviewed,
  newIds,
  onSelectEvent,
}: AccessEventFeedProps) {
  const containerRef = useRef<HTMLUListElement>(null)
  // `pinned` is true while the operator is at (or hasn't left) the top of
  // the list — new events render immediately. Scrolling away freezes the
  // view at `frozenId` (the newest event id at that moment) so newly
  // arriving events don't shove the rows the operator is reading further
  // down; they're held behind the "N event baru" pill instead (screen-plan
  // S-40: "scroll-pinning saat operator membaca").
  const [pinned, setPinned] = useState(true)
  const [frozenId, setFrozenId] = useState<string | null>(null)

  const pendingCount = useMemo(() => {
    if (pinned || frozenId === null) return 0
    const idx = events.findIndex((event) => event.id === frozenId)
    return idx === -1 ? events.length : idx
  }, [events, pinned, frozenId])

  const visibleEvents = pinned ? events : events.slice(pendingCount)

  function handleScroll(): void {
    const el = containerRef.current
    if (!el) return
    const atTop = el.scrollTop <= SCROLL_TOP_THRESHOLD_PX
    if (atTop) {
      setPinned(true)
    } else if (pinned) {
      setFrozenId(events[0]?.id ?? null)
      setPinned(false)
    }
  }

  function catchUp(): void {
    containerRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    setPinned(true)
  }

  if (isLoading && events.length === 0) {
    return (
      <ul className="access-event-feed access-event-feed--skeleton" aria-busy="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <li key={i} className="access-event-item access-event-item--skeleton" />
        ))}
      </ul>
    )
  }

  if (events.length === 0) {
    return (
      <div className="access-event-feed-empty">
        <p className="access-event-feed-empty__title">Belum ada aktivitas</p>
        <p className="access-event-feed-empty__hint">
          Event akses hari ini akan muncul di sini secara real-time.
        </p>
      </div>
    )
  }

  return (
    <div className="access-event-feed-wrap">
      {pendingCount > 0 && (
        <button type="button" className="access-event-feed__catch-up" onClick={catchUp}>
          {pendingCount} event baru — tampilkan
        </button>
      )}
      <ul className="access-event-feed" ref={containerRef} onScroll={handleScroll}>
        {visibleEvents.map((event) => (
          <AccessEventItem
            key={event.id}
            event={event}
            deviceName={deviceNames.get(event.device_id) ?? null}
            isNew={newIds.has(event.id)}
            reviewed={reviewedSpoofIds.has(event.id)}
            onMarkReviewed={onMarkReviewed}
            onSelect={onSelectEvent}
          />
        ))}
      </ul>
    </div>
  )
}
