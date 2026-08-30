import { useQuery } from '@tanstack/react-query'
import { getUser } from '../user-management/api'

/**
 * Resolves `matched_user_id` to a display name, fetch-on-demand with a long
 * `staleTime` so the same user isn't re-fetched every time another event
 * for them arrives in the feed (task instructions: "cukup fetch-on-demand
 * dengan cache sederhana ... supaya user yang sama tidak di-fetch ulang").
 * TanStack Query's own cache (keyed by `['user', id]`) does this for us —
 * no extra Map needed — and de-dupes concurrent requests for the same id
 * across every `AccessEventItem` mounted at once.
 */
export function useUserName(userId: string | null): {
  name: string | null
  isLoading: boolean
} {
  const query = useQuery({
    queryKey: ['user', userId],
    queryFn: () => getUser(userId as string),
    enabled: userId !== null,
    staleTime: 10 * 60 * 1000,
    retry: 0,
  })

  if (userId === null) return { name: null, isLoading: false }
  return { name: query.data?.full_name ?? null, isLoading: query.isLoading }
}
