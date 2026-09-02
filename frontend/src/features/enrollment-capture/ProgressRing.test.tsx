import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProgressRing from './ProgressRing'
import { createInitialSectorState } from './clockSectors'
import { CAPTURE_POSITIONS, CLOCK_POSITIONS } from './types'

describe('ProgressRing — directional guidance ("animasi arahan")', () => {
  it('renders no target marker when targetPosition is omitted/null', () => {
    render(<ProgressRing status={createInitialSectorState()} />)
    expect(screen.queryByTestId('ring-target-marker')).not.toBeInTheDocument()
  })

  it('renders a pulsing target marker labelled with the head movement to make', () => {
    render(<ProgressRing status={createInitialSectorState()} targetPosition={3} />)
    const marker = screen.getByTestId('ring-target-marker')
    expect(marker).toBeInTheDocument()
    expect(marker).toHaveClass('capture-ring-target-marker')
    // The instruction is the movement, not the hour number — "jam 3" means
    // nothing to a subject being asked to turn their head.
    expect(marker).toHaveTextContent(/agak menoleh ke kanan/)
  })

  it('renders one arc per captured position and nothing else', () => {
    render(<ProgressRing status={createInitialSectorState()} targetPosition={12} />)

    for (const position of CAPTURE_POSITIONS) {
      expect(screen.getByTestId(`sector-${position}`)).toBeInTheDocument()
    }
    // The uncaptured hours must not be drawn: showing twelve narrow sectors
    // would promise 30-degree precision the detector cannot deliver.
    for (const position of CLOCK_POSITIONS) {
      if (CAPTURE_POSITIONS.includes(position)) continue
      expect(screen.queryByTestId(`sector-${position}`)).not.toBeInTheDocument()
    }
  })

  it('spells out the movement for every captured position', () => {
    render(<ProgressRing status={createInitialSectorState()} />)
    const expected: Record<number, RegExp> = {
      12: /agak mendongak/,
      3: /agak menoleh ke kanan/,
      6: /agak menunduk/,
      9: /agak menoleh ke kiri/,
    }
    for (const position of CAPTURE_POSITIONS) {
      expect(screen.getByTestId(`sector-${position}`)).toHaveTextContent(
        expected[position],
      )
    }
  })
})
