import type { Landmarks68 } from './types'

/**
 * Browser-side face detection + 68-point landmarks via
 * @vladmandic/face-api (a maintained TensorFlow.js fork of face-api.js).
 *
 * Why this library: it runs fully client-side (WASM/CPU backend, no
 * server-side inference call, matching the "detect in the browser" ask),
 * ships TypeScript types, and its `tinyFaceDetector` +
 * `faceLandmark68TinyNet` models together are ~260KB — small enough to
 * self-host under `public/models` (copied from the npm package at build
 * time) so the capture screen has no runtime dependency on a CDN.
 * Alternatives considered: the original unmaintained `face-api.js`
 * (same API, but stale TF.js peer dep); MediaPipe Face Detection/Mesh
 * (more accurate, but ships as a WASM+model bundle fetched from Google's
 * CDN by default and has a heavier integration surface for a browser-only
 * SPA). @vladmandic/face-api was the best fit for "gampang diinstal &
 * jalan di browser tanpa server-side inference".
 */

const MODEL_URL = '/models'

// Loaded dynamically (not at module top-level): @vladmandic/face-api's
// entry point branches on Node vs. browser at import time, and this
// module is imported transitively by the app's route table. A static
// top-level import would force that branch to run during any test (e.g.
// vitest/Node) that merely imports the routes, even ones that never
// render the capture page. Deferring the import to when detection is
// actually needed keeps this module side-effect-free until used.
type FaceApiModule = typeof import('@vladmandic/face-api')
let faceApiPromise: Promise<FaceApiModule> | null = null
function loadFaceApi(): Promise<FaceApiModule> {
  faceApiPromise ??= import('@vladmandic/face-api')
  return faceApiPromise
}

let modelsLoaded: Promise<void> | null = null

export function loadFaceDetectionModels(): Promise<void> {
  if (!modelsLoaded) {
    modelsLoaded = loadFaceApi().then((faceapi) =>
      Promise.all([
        faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
        faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODEL_URL),
      ]).then(() => undefined),
    )
  }
  return modelsLoaded
}

export interface DetectionResult {
  faceInFrame: boolean
  landmarks: Landmarks68 | null
}

/** Detect a single face + landmarks in the given frame. Returns
 * `faceInFrame: false` when nothing is detected (never throws for "no
 * face" — that is an expected, common state during capture). */
export async function detectFace(
  input: HTMLCanvasElement | HTMLVideoElement,
): Promise<DetectionResult> {
  const faceapi = await loadFaceApi()
  const detection = await faceapi
    .detectSingleFace(input, new faceapi.TinyFaceDetectorOptions())
    .withFaceLandmarks(true)

  if (!detection) return { faceInFrame: false, landmarks: null }

  const landmarks = detection.landmarks
    .positions as unknown as Landmarks68
  return { faceInFrame: true, landmarks }
}
