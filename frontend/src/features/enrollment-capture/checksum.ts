export interface Sha256Digest {
  /** 64 lowercase hex chars — what BE-06's presign endpoint expects in the
   * request body (`sha256` field). */
  hex: string
  /** Base64 of the raw 32-byte digest — what S3 expects in the
   * `x-amz-checksum-sha256` request header on the PUT. Must be computed
   * from the SAME bytes as `hex`, or S3 rejects the upload. */
  base64: string
}

function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

function bufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

/**
 * Compute the SHA-256 digest of a Blob entirely in-browser via
 * SubtleCrypto — the media bytes never touch our backend, only S3 (and
 * only the claimed hash is sent to the backend at presign time).
 */
export async function computeSha256(blob: Blob): Promise<Sha256Digest> {
  const buffer = await blob.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return { hex: bufferToHex(digest), base64: bufferToBase64(digest) }
}
