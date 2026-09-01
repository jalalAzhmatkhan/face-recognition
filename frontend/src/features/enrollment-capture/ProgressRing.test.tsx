import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProgressRing from './ProgressRing'
import { createInitialSectorState } from './clockSectors'

describe('ProgressRing — directional guidance ("animasi arahan")', () => {
  it('renders no target marker when targetPosition is omitted/null', () => {
    render(<ProgressRing status={createInitialSectorState()} />)
    expect(screen.queryByTestId('ring-target-marker')).not.toBeInTheDocument()
  })

  it('renders a pulsing target marker pointing at the given clock position', () => {
    render(<ProgressRing status={createInitialSectorState()} targetPosition={3} />)
    const marker = screen.getByTestId('ring-target-marker')
    expect(marker).toBeInTheDocument()
    expect(marker).toHaveClass('capture-ring-target-marker')
    expect(marker).toHaveTextContent('Selanjutnya: arahkan wajah ke jam 3')
  })

  it('still renders all 12 sectors regardless of the target marker', () => {
    render(<ProgressRing status={createInitialSectorState()} targetPosition={12} />)
    for (let position = 1; position <= 12; position += 1) {
      expect(screen.getByTestId(`sector-${position}`)).toBeInTheDocument()
    }
  })
})
