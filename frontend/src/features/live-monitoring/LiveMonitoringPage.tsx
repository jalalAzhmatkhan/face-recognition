import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import AccessEventDrawer from './AccessEventDrawer'
import AccessEventFeed from './AccessEventFeed'
import DeviceStatusPanel from './DeviceStatusPanel'
import FilterBar from './FilterBar'
import OfflineDeviceBanner from './OfflineDeviceBanner'
import SpoofBanner from './SpoofBanner'
import TodaySummaryPanel from './TodaySummaryPanel'
import { fetchTodaySummary, listDevices } from './api'
import { openAccessEventStream } from './sseClient'
import type { AccessDecision, AccessEventPayload, ConnectionStatus, TodaySummary } from './types'
import { EMPTY_TODAY_SUMMARY } from './types'
import { getCurrentRole } from '../../lib/authToken'
import './LiveMonitoring.css'

/** Cap on in-memory feed items — task instructions call this out explicitly
 * as a deliberate MVP choice: an operator console left open for hours
 * shouldn't grow its DOM/JS heap without bound. Oldest items are dropped
 * silently once the cap is hit; nothing is persisted beyond this session
 * anyway (the real audit trail is `GET /access-events`, out of scope here
 * per S-42, not built yet). */
const MAX_FEED_EVENTS = 200

/** How long a freshly-arrived item keeps its "new" highlight/slide-in class
 * before `AccessEventItem` treats it as a normal row (CSS transition only,
 * no animation library — task instructions). */
const NEW_ITEM_HIGHLIGHT_MS = 2500

const DEVICE_POLL_INTERVAL_MS = 20_000

/** S-40 Live Monitoring — the one screen in FE-06's scope (screen-plan
 * §S-40). Orchestrates: SSE feed connection + reconnect, device/decision
 * filters, the today-summary panel (REST snapshot + local SSE increments),
 * the device status panel (polled REST, not SSE), and the two safety
 * banners (spoof-suspected, device offline / fail-secure). */
export default function LiveMonitoringPage() {
  const role = getCurrentRole()
  const canSeeDevices = role === 'ADMIN' || role === 'OPERATOR'

  const [deviceFilter, setDeviceFilter] = useState('')
  const [decisionFilter, setDecisionFilter] = useState<AccessDecision | ''>('')

  const [events, setEvents] = useState<AccessEventPayload[]>([])
  const [newIds, setNewIds] = useState<Set<string>>(new Set())
  const [reviewedSpoofIds, setReviewedSpoofIds] = useState<Set<string>>(new Set())
  const [selectedEvent, setSelectedEvent] = useState<AccessEventPayload | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting')
  const [localIncrements, setLocalIncrements] = useState<TodaySummary>(EMPTY_TODAY_SUMMARY)

  const devicesQuery = useQuery({
    queryKey: ['devices', 'live-monitoring'],
    queryFn: () => listDevices({ limit: 200 }),
    enabled: canSeeDevices,
    refetchInterval: DEVICE_POLL_INTERVAL_MS,
  })

  const summaryQuery = useQuery({
    queryKey: ['access-events', 'today-summary', deviceFilter],
    queryFn: () => fetchTodaySummary(deviceFilter || undefined),
  })

  const deviceNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const device of devicesQuery.data?.items ?? []) map.set(device.id, device.name)
    return map
  }, [devicesQuery.data])

  // Reset per-filter local state whenever the operator changes device or
  // decision filter — the old feed/counters aren't necessarily relevant
  // under a new filter (task instructions: "reset feed yang tampil"). Done
  // as a render-time state adjustment (React's documented pattern for
  // "resetting state when a prop changes") rather than a `useEffect`, so it
  // takes effect before the stale list ever paints instead of one render
  // later.
  const filterKey = `${deviceFilter}|${decisionFilter}`
  const [syncedFilterKey, setSyncedFilterKey] = useState(filterKey)
  if (filterKey !== syncedFilterKey) {
    setSyncedFilterKey(filterKey)
    setEvents([])
    setLocalIncrements(EMPTY_TODAY_SUMMARY)
  }

  const highlightTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  const handleEvent = useCallback((event: AccessEventPayload) => {
    setEvents((prev) => [event, ...prev].slice(0, MAX_FEED_EVENTS))
    setLocalIncrements((prev) => ({ ...prev, [event.decision]: prev[event.decision] + 1 }))

    setNewIds((prev) => {
      const next = new Set(prev)
      next.add(event.id)
      return next
    })
    const timer = setTimeout(() => {
      setNewIds((prev) => {
        const next = new Set(prev)
        next.delete(event.id)
        return next
      })
      highlightTimersRef.current.delete(event.id)
    }, NEW_ITEM_HIGHLIGHT_MS)
    highlightTimersRef.current.set(event.id, timer)
  }, [])

  useEffect(() => {
    const handle = openAccessEventStream({
      deviceId: deviceFilter || undefined,
      decision: decisionFilter || undefined,
      onEvent: handleEvent,
      onStatusChange: setConnectionStatus,
    })
    const timersAtEffectTime = highlightTimersRef.current
    return () => {
      handle.close()
      for (const timer of timersAtEffectTime.values()) clearTimeout(timer)
      timersAtEffectTime.clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceFilter, decisionFilter])

  const summary: TodaySummary = useMemo(() => {
    const base = summaryQuery.data ?? EMPTY_TODAY_SUMMARY
    return {
      GRANTED: base.GRANTED + localIncrements.GRANTED,
      DENIED: base.DENIED + localIncrements.DENIED,
      UNKNOWN: base.UNKNOWN + localIncrements.UNKNOWN,
      SPOOF_SUSPECTED: base.SPOOF_SUSPECTED + localIncrements.SPOOF_SUSPECTED,
    }
  }, [summaryQuery.data, localIncrements])

  const unreviewedSpoofCount = useMemo(
    () =>
      events.filter((e) => e.decision === 'SPOOF_SUSPECTED' && !reviewedSpoofIds.has(e.id))
        .length,
    [events, reviewedSpoofIds],
  )

  const relevantDevices = useMemo(() => {
    const all = devicesQuery.data?.items ?? []
    if (!deviceFilter) return all
    return all.filter((d) => d.id === deviceFilter)
  }, [devicesQuery.data, deviceFilter])

  function markReviewed(id: string): void {
    setReviewedSpoofIds((prev) => new Set(prev).add(id))
  }

  return (
    <section className="live-monitoring-page">
      <header className="live-monitoring-page__header">
        <h1>Live Monitoring</h1>
      </header>

      <SpoofBanner unreviewedCount={unreviewedSpoofCount} />
      {canSeeDevices && <OfflineDeviceBanner devices={relevantDevices} />}

      <FilterBar
        deviceId={deviceFilter}
        onDeviceIdChange={setDeviceFilter}
        devices={canSeeDevices ? devicesQuery.data?.items ?? [] : []}
        decision={decisionFilter}
        onDecisionChange={setDecisionFilter}
        connectionStatus={connectionStatus}
      />

      <div className="live-monitoring-page__body">
        <div className="live-monitoring-page__feed">
          <AccessEventFeed
            events={events}
            deviceNames={deviceNames}
            isLoading={connectionStatus === 'connecting' && events.length === 0}
            reviewedSpoofIds={reviewedSpoofIds}
            onMarkReviewed={markReviewed}
            newIds={newIds}
            onSelectEvent={setSelectedEvent}
          />
        </div>
        <aside className="live-monitoring-page__sidebar">
          <TodaySummaryPanel summary={summary} isLoading={summaryQuery.isLoading} />
          <DeviceStatusPanel
            devices={devicesQuery.data?.items ?? null}
            isLoading={devicesQuery.isLoading}
            allowedForRole={canSeeDevices}
          />
        </aside>
      </div>

      {selectedEvent && (
        <AccessEventDrawer
          event={selectedEvent}
          deviceName={deviceNames.get(selectedEvent.device_id) ?? null}
          reviewed={reviewedSpoofIds.has(selectedEvent.id)}
          onMarkReviewed={markReviewed}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </section>
  )
}
