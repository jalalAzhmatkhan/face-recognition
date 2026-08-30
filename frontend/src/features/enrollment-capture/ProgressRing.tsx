import { CLOCK_POSITIONS } from './types'
import type { SectorState } from './types'

interface ProgressRingProps {
  status: SectorState
  size?: number
}

const SECTOR_COLOR: Record<SectorState[keyof SectorState], string> = {
  pending: 'var(--capture-sector-pending)',
  active: 'var(--capture-sector-active)',
  done: 'var(--capture-sector-done)',
  poor: 'var(--capture-sector-poor)',
}

/**
 * 12-sector progress ring around the face oval (screen-plan S-30, step
 * 3b). Every sector must be individually confirmed — there is no
 * "auto-pass" sector, per FSD-AI.md ASM-03 (CORRECTED 2026-08-30).
 */
export default function ProgressRing({ status, size = 320 }: ProgressRingProps) {
  const center = size / 2
  const outerRadius = center - 8
  const innerRadius = outerRadius - 22
  const gapDeg = 3

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="Progress cakupan 12 posisi jam"
    >
      <ellipse
        cx={center}
        cy={center}
        rx={innerRadius - 10}
        ry={innerRadius - 4}
        fill="none"
        stroke="var(--border-strong)"
        strokeWidth={2}
        strokeDasharray="4 4"
      />
      {CLOCK_POSITIONS.map((position) => {
        const sectorAngle = 30
        const startDeg = position * 30 - sectorAngle / 2 + gapDeg / 2 - 90
        const endDeg = position * 30 + sectorAngle / 2 - gapDeg / 2 - 90
        const toRad = (deg: number) => (deg * Math.PI) / 180
        const p1 = {
          x: center + outerRadius * Math.cos(toRad(startDeg)),
          y: center + outerRadius * Math.sin(toRad(startDeg)),
        }
        const p2 = {
          x: center + outerRadius * Math.cos(toRad(endDeg)),
          y: center + outerRadius * Math.sin(toRad(endDeg)),
        }
        const p3 = {
          x: center + innerRadius * Math.cos(toRad(endDeg)),
          y: center + innerRadius * Math.sin(toRad(endDeg)),
        }
        const p4 = {
          x: center + innerRadius * Math.cos(toRad(startDeg)),
          y: center + innerRadius * Math.sin(toRad(startDeg)),
        }
        const path = [
          `M ${p1.x} ${p1.y}`,
          `A ${outerRadius} ${outerRadius} 0 0 1 ${p2.x} ${p2.y}`,
          `L ${p3.x} ${p3.y}`,
          `A ${innerRadius} ${innerRadius} 0 0 0 ${p4.x} ${p4.y}`,
          'Z',
        ].join(' ')

        const sectorStatus = status[position]
        return (
          <path
            key={position}
            d={path}
            fill={SECTOR_COLOR[sectorStatus]}
            data-testid={`sector-${position}`}
            data-status={sectorStatus}
            style={{
              transition:
                'fill var(--dur-slow) var(--ease-spring)',
            }}
          >
            <title>
              Jam {position}: {sectorStatus === 'done' ? 'selesai' : sectorStatus === 'poor' ? 'kualitas kurang' : sectorStatus === 'active' ? 'sedang direkam' : 'belum'}
            </title>
          </path>
        )
      })}
    </svg>
  )
}
