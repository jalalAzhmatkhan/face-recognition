import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import './ActionsMenu.css'

interface MenuPosition {
  top: number
  right: number
}

/** Where to render the popover (menu or confirm) relative to the trigger,
 * in viewport coordinates — computed fresh each time it opens/repositions.
 * Right-aligned to the trigger's right edge (matches the CSS `right: 0`
 * this replaces) so it never needs to know the popover's own width. */
function computePosition(trigger: HTMLElement): MenuPosition {
  const rect = trigger.getBoundingClientRect()
  return {
    top: rect.bottom + 4,
    right: window.innerWidth - rect.right,
  }
}

/**
 * Shared "⋮" icon-button + context-menu primitive for table "Aksi" columns
 * that have MORE THAN ONE possible action per row (bugfix:
 * users-actions-menu). A column with a single, always-shown link (e.g.
 * "Detail"/"Review" elsewhere in this app) stays a plain link — this
 * component exists specifically for the case that used to render several
 * conditionally-visible buttons side by side and got visually cramped.
 *
 * The open menu/confirm popover is rendered through a portal into
 * `document.body`, positioned via `position: fixed` from the trigger's own
 * `getBoundingClientRect()` (bugfix: actions-menu-table-clip). Every table
 * using this component wraps its `<table>` in a plain `overflowX: 'auto'`
 * div for horizontal scrolling on narrow screens — but CSS's overflow
 * rules mean setting overflow-x alone makes the *other* axis compute to
 * `auto` too, not `visible` (https://www.w3.org/TR/css-overflow-3/#overflow-control),
 * so the old `position: absolute` popover (anchored inside that div) was
 * clipped by it, and its own presence pushed the div's scrollable content
 * height past its border box, adding a spurious vertical scrollbar to the
 * table itself. Escaping to a body-level portal sidesteps that clipping
 * entirely regardless of what any ancestor's overflow is set to.
 *
 * Two render states, controlled by the caller (NOT internal state), so a
 * two-step destructive action (e.g. "Yakin nonaktifkan?") can replace the
 * menu with a confirm popover anchored in the exact same place:
 * - `renderConfirm` provided → shows that instead of the trigger+menu,
 *   trigger becomes a disabled placeholder so the row's layout doesn't
 *   jump.
 * - `renderConfirm` absent → normal trigger; clicking opens `children`
 *   (the menu items), closed by clicking the trigger again, clicking
 *   outside, Escape, or an item calling the `closeMenu` callback it's
 *   handed.
 */
export default function ActionsMenu({
  label = 'Aksi lainnya',
  renderConfirm,
  children,
}: {
  label?: string
  renderConfirm?: () => ReactNode
  children: (closeMenu: () => void) => ReactNode
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [position, setPosition] = useState<MenuPosition | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

  const showingPopover = isOpen || !!renderConfirm

  // Recompute position synchronously whenever the popover (menu or confirm)
  // is about to paint, so it never flashes at a stale/zero position.
  useLayoutEffect(() => {
    if (!showingPopover || !triggerRef.current) return
    setPosition(computePosition(triggerRef.current))
  }, [showingPopover])

  useEffect(() => {
    if (!showingPopover) return

    function isOutside(target: EventTarget | null): boolean {
      const node = target as Node
      return !triggerRef.current?.contains(node) && !popoverRef.current?.contains(node)
    }

    function handlePointerDown(event: MouseEvent) {
      // Only the menu (not a confirm popover, which has its own explicit
      // Batal/confirm buttons and no "click outside to dismiss" affordance
      // by design) closes on an outside click.
      if (isOpen && isOutside(event.target)) setIsOpen(false)
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && isOpen) setIsOpen(false)
    }
    // The popover's fixed position is computed once on open from the
    // trigger's rect — if the page scrolls/resizes while it's open, that
    // rect (and any right-aligned math derived from window.innerWidth)
    // goes stale. Reposition on resize; scrolling closes the menu outright
    // (matches this component's existing "click outside closes" spirit,
    // and avoids tracking every scrollable ancestor).
    function handleScroll() {
      if (isOpen) setIsOpen(false)
      else if (triggerRef.current) setPosition(computePosition(triggerRef.current))
    }
    function handleResize() {
      if (triggerRef.current) setPosition(computePosition(triggerRef.current))
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', handleResize)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('resize', handleResize)
    }
  }, [isOpen, showingPopover])

  if (renderConfirm) {
    return (
      <div className="actions-menu">
        <button
          ref={triggerRef}
          type="button"
          className="actions-menu__trigger"
          disabled
          aria-label={label}
        >
          ⋮
        </button>
        {position &&
          createPortal(
            <div ref={popoverRef} className="actions-menu__portal" style={{ top: position.top, right: position.right }}>
              {renderConfirm()}
            </div>,
            document.body,
          )}
      </div>
    )
  }

  return (
    <div className="actions-menu">
      <button
        ref={triggerRef}
        type="button"
        className="actions-menu__trigger"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        ⋮
      </button>
      {isOpen &&
        position &&
        createPortal(
          <div
            ref={popoverRef}
            className="actions-menu__portal actions-menu__menu"
            role="menu"
            style={{ top: position.top, right: position.right }}
          >
            {children(() => setIsOpen(false))}
          </div>,
          document.body,
        )}
    </div>
  )
}

type ItemVariant = 'default' | 'danger' | 'warning'

function variantClassName(variant: ItemVariant): string {
  return variant === 'default' ? 'actions-menu__item' : `actions-menu__item actions-menu__item--${variant}`
}

/** One menu item, either a navigation `Link` (pass `to`) or an action
 * `button` (pass `onClick`) — exactly one of the two should be given. */
export function ActionsMenuItem({
  to,
  onClick,
  disabled,
  variant = 'default',
  children,
}: {
  to?: string
  onClick?: () => void
  disabled?: boolean
  variant?: ItemVariant
  children: ReactNode
}) {
  if (to) {
    return (
      <Link to={to} className={variantClassName(variant)} role="menuitem">
        {children}
      </Link>
    )
  }
  return (
    <button
      type="button"
      role="menuitem"
      className={variantClassName(variant)}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

/** Confirm popover for a two-step action, anchored via `ActionsMenu`'s
 * `renderConfirm` slot. `tone` picks the danger/warning color scheme (same
 * semantic split already used by this app's inline confirm buttons —
 * danger for permanent-ish actions like offboarding/disabling, warning for
 * disruptive-but-reversible ones like rotating a credential). */
export function ActionsMenuConfirm({
  tone,
  text,
  confirmLabel,
  pendingLabel,
  isPending,
  disabled,
  onConfirm,
  onCancel,
}: {
  tone: 'danger' | 'warning'
  text: string
  confirmLabel: string
  pendingLabel: string
  isPending: boolean
  disabled?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div
      className={`actions-menu__confirm actions-menu__confirm--${tone}`}
      role="alertdialog"
      aria-label={text}
    >
      <p className="actions-menu__confirm-text">{text}</p>
      <div className="actions-menu__confirm-buttons">
        <button type="button" disabled={disabled} onClick={onConfirm}>
          {isPending ? pendingLabel : confirmLabel}
        </button>
        <button type="button" onClick={onCancel}>
          Batal
        </button>
      </div>
    </div>
  )
}
