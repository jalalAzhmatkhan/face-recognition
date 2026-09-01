import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ActionsMenu, { ActionsMenuConfirm, ActionsMenuItem } from './ActionsMenu'

afterEach(() => cleanup())

function renderMenu(onClick = vi.fn()) {
  return render(
    <MemoryRouter>
      <ActionsMenu>
        {(closeMenu) => (
          <>
            <ActionsMenuItem
              onClick={() => {
                onClick()
                closeMenu()
              }}
            >
              Do thing
            </ActionsMenuItem>
            <ActionsMenuItem to="/somewhere">Go somewhere</ActionsMenuItem>
          </>
        )}
      </ActionsMenu>
    </MemoryRouter>,
  )
}

describe('ActionsMenu', () => {
  it('is closed by default', () => {
    renderMenu()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('opens the menu on trigger click and shows items', () => {
    renderMenu()
    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Do thing' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Go somewhere' })).toBeInTheDocument()
  })

  it('toggles closed when the trigger is clicked again', () => {
    renderMenu()
    const trigger = screen.getByRole('button', { name: 'Aksi lainnya' })
    fireEvent.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.click(trigger)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('calls the item onClick and closes the menu via the closeMenu callback', () => {
    const onClick = vi.fn()
    renderMenu(onClick)
    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Do thing' }))
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes when clicking outside the menu', () => {
    render(
      <MemoryRouter>
        <div>
          <span data-testid="outside">outside</span>
          <ActionsMenu>{() => <ActionsMenuItem onClick={() => {}}>Item</ActionsMenuItem>}</ActionsMenu>
        </div>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByTestId('outside'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('renders the open menu outside any overflow-clipping ancestor (bugfix: actions-menu-table-clip)', () => {
    // Reproduces the table wrapper pattern used by UsersPage/DevicesPage
    // (`<div style={{ overflowX: 'auto' }}><table>...`) — CSS's overflow
    // rules mean setting overflow-x alone makes overflow-y compute to
    // `auto` too, so a menu nested (not portaled) inside this div would be
    // clipped and add a spurious vertical scrollbar to the wrapper.
    const { container } = render(
      <MemoryRouter>
        <div data-testid="table-wrapper" style={{ overflowX: 'auto' }}>
          <table>
            <tbody>
              <tr>
                <td>
                  <ActionsMenu>{() => <ActionsMenuItem onClick={() => {}}>Item</ActionsMenuItem>}</ActionsMenu>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    const menu = screen.getByRole('menu')
    expect(menu).toBeInTheDocument()
    // The menu is a sibling of the render root (portaled to document.body),
    // not a descendant of the overflow-clipping wrapper or even of this
    // test's own render container.
    expect(container.contains(menu)).toBe(false)
    expect(screen.getByTestId('table-wrapper').contains(menu)).toBe(false)
    expect(document.body.contains(menu)).toBe(true)
  })

  it('closes on Escape', () => {
    renderMenu()
    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('renders the confirm popover instead of the menu when renderConfirm is provided', () => {
    render(
      <MemoryRouter>
        <ActionsMenu
          renderConfirm={() => (
            <ActionsMenuConfirm
              tone="danger"
              text="Yakin?"
              confirmLabel="Ya"
              pendingLabel="Memproses..."
              isPending={false}
              onConfirm={() => {}}
              onCancel={() => {}}
            />
          )}
        >
          {() => <ActionsMenuItem onClick={() => {}}>Item</ActionsMenuItem>}
        </ActionsMenu>
      </MemoryRouter>,
    )
    expect(screen.getByText('Yakin?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Aksi lainnya' })).toBeDisabled()
    // The trigger is disabled and there's no toggle-able menu behind it.
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('confirm popover calls onConfirm/onCancel correctly', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ActionsMenuConfirm
        tone="warning"
        text="Lanjutkan?"
        confirmLabel="Ya, Lanjut"
        pendingLabel="Memproses..."
        isPending={false}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ya, Lanjut' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Batal' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('confirm popover shows the pending label while isPending', () => {
    render(
      <ActionsMenuConfirm
        tone="danger"
        text="Yakin?"
        confirmLabel="Ya"
        pendingLabel="Memproses..."
        isPending
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: 'Memproses...' })).toBeInTheDocument()
  })
})
