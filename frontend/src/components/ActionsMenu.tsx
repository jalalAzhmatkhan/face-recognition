import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import './ActionsMenu.css'

/**
 * Shared "⋮" icon-button + context-menu primitive for table "Aksi" columns
 * that have MORE THAN ONE possible action per row (bugfix:
 * users-actions-menu). A column with a single, always-shown link (e.g.
 * "Detail"/"Review" elsewhere in this app) stays a plain link — this
 * component exists specifically for the case that used to render several
 * conditionally-visible buttons side by side and got visually cramped.
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
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false)
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setIsOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  if (renderConfirm) {
    return (
      <div className="actions-menu" ref={containerRef}>
        <button type="button" className="actions-menu__trigger" disabled aria-label={label}>
          ⋮
        </button>
        {renderConfirm()}
      </div>
    )
  }

  return (
    <div className="actions-menu" ref={containerRef}>
      <button
        type="button"
        className="actions-menu__trigger"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        ⋮
      </button>
      {isOpen && (
        <div className="actions-menu__menu" role="menu">
          {children(() => setIsOpen(false))}
        </div>
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
