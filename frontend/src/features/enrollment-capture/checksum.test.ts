import { describe, expect, it } from 'vitest'
import { computeSha256 } from './checksum'

describe('computeSha256', () => {
  it('matches the known SHA-256 of an empty blob (hex and base64 of the same bytes)', async () => {
    const digest = await computeSha256(new Blob([]))
    expect(digest.hex).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    )
    expect(digest.base64).toBe('47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=')
  })

  it('matches the known SHA-256 of "hello world"', async () => {
    const digest = await computeSha256(new Blob(['hello world']))
    expect(digest.hex).toBe(
      'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9',
    )
    expect(digest.base64).toBe('uU0nuZNNPgilLlLX2n2r+sSE7+N6U4DukIj3rOLvzek=')
  })

  it('produces a 64-char lowercase hex string and a base64 string decoding to 32 bytes', async () => {
    const digest = await computeSha256(new Blob(['sample media bytes']))
    expect(digest.hex).toMatch(/^[0-9a-f]{64}$/)
    expect(atob(digest.base64)).toHaveLength(32)
  })
})
