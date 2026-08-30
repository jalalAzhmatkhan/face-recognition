# FRAC Console — Frontend

Web console untuk Face Recognition Access Control (enrollment capture 360°, manajemen user, monitoring akses).

## Stack (ASM-11 CONFIRMED)

- React 19 + TypeScript (strict) + Vite 8
- TanStack Query v5 (server state) — client di `src/app/queryClient.ts`
- React Router v7 (`react-router-dom`) — route definitions di `src/app/routes.tsx`
- ESLint (flat config) + Vitest + Testing Library

## Scripts

| Script | Fungsi |
|---|---|
| `npm run dev` | Dev server |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc -b` |
| `npm run test` | Vitest (run once, CI) |
| `npm run build` | Typecheck + production build |

## Struktur

```
src/
  app/        # shell: routes, AppLayout (sidebar), queryClient, useTheme
  pages/      # satu file per screen (screen-plan S-xx) — placeholder di FE-01
  styles/
    tokens.css  # design tokens 1:1 dari documentation/uiux/design-tokens.md §9
  index.css   # reset + aplikasi token dasar
```

## Design tokens & theming

`src/styles/tokens.css` menyalin CSS variables dari `documentation/uiux/design-tokens.md` (jangan edit nilai tanpa update dokumen tokens). Light default; dark via `data-theme="dark"` pada `<html>` atau `prefers-color-scheme` (override user disimpan di `localStorage`, lihat `src/app/useTheme.ts`). `prefers-reduced-motion` dihormati (durasi → 0).

## Aturan

- Media capture TIDAK pernah disimpan lokal — upload langsung ke S3 via presigned URL dari backend.
- Frontend hanya bicara ke Core API; tidak ada kredensial di kode.
