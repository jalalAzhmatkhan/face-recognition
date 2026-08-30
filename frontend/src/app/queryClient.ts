import { QueryClient } from '@tanstack/react-query'

/**
 * Shared TanStack Query client. Defaults tuned for an operational console:
 * retry once (errors surfaced fast to the operator), no refetch storm on focus.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})
