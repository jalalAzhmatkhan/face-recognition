import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildPresignRequestBody,
  completeEnrollment,
  presignMedia,
  uploadToS3,
} from './apiClient'

const ACCESS_TOKEN_KEY = 'frac_access_token'

describe('buildPresignRequestBody', () => {
  it('maps a local file description to the BE-06 request shape', () => {
    const body = buildPresignRequestBody('photo', {
      contentType: 'image/jpeg',
      size: 12345,
      sha256Hex: 'a'.repeat(64),
    })
    expect(body).toEqual({
      kind: 'photo',
      content_type: 'image/jpeg',
      size: 12345,
      sha256: 'a'.repeat(64),
    })
  })
})

describe('presignMedia / completeEnrollment (authenticated requests)', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'test-token')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    vi.unstubAllGlobals()
  })

  it('presignMedia attaches the bearer token and posts the exact BE-06 shape', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          upload_url: 'https://s3.example.com/upload',
          s3_key: 'enrollment/u1/s1/photo_1.jpg',
          expires_at: '2026-08-30T00:05:00Z',
        }),
        { status: 201 },
      ),
    )

    const body = buildPresignRequestBody('photo', {
      contentType: 'image/jpeg',
      size: 100,
      sha256Hex: 'b'.repeat(64),
    })
    const result = await presignMedia('enroll-1', body)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1/media/presign')
    expect(init.method).toBe('POST')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
    expect(JSON.parse(init.body)).toEqual(body)
    expect(result.upload_url).toBe('https://s3.example.com/upload')
  })

  it('completeEnrollment posts with no body and returns the new state', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 'enroll-1', state: 'QC_RUNNING' }), {
        status: 202,
      }),
    )

    const result = await completeEnrollment('enroll-1')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1/complete')
    expect(init.method).toBe('POST')
    expect(result.state).toBe('QC_RUNNING')
  })

  it('throws ApiError with status and body on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ reasons: [{ code: 'missing_photo' }] }),
        { status: 422 },
      ),
    )

    await expect(completeEnrollment('enroll-1')).rejects.toMatchObject({
      status: 422,
    })
  })
})

describe('uploadToS3', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('PUTs the blob straight to the presigned URL with the checksum header, no auth header', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }))

    await uploadToS3(
      'https://s3.example.com/upload?sig=abc',
      new Blob(['data']),
      'checksum-base64==',
      'image/jpeg',
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://s3.example.com/upload?sig=abc')
    expect(init.method).toBe('PUT')
    expect(init.headers['x-amz-checksum-sha256']).toBe('checksum-base64==')
    expect(init.headers['Content-Type']).toBe('image/jpeg')
    expect(init.headers.Authorization).toBeUndefined()
  })

  it('throws ApiError when S3 rejects the upload', async () => {
    fetchMock.mockResolvedValue(
      new Response('checksum mismatch', { status: 400 }),
    )

    await expect(
      uploadToS3('https://s3.example.com/upload', new Blob(['x']), 'abc', 'video/webm'),
    ).rejects.toBeInstanceOf(ApiError)
  })
})
