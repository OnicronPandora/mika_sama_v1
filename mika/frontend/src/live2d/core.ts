// Cubism Core: Live2D's own script (Live2D Proprietary Software License, not on npm), copied into public/ by hand
// (README). easy-live2d reads it the moment it is imported, so the avatar page loads the Core first and imports
// the Live2D code after it; a missing Core then only breaks the avatar, not the other pages.

export const CORE_URL = '/live2dcubismcore.min.js'

let loading: Promise<void> | undefined

/** Loads the Core once, with a <script> tag. */
export function loadCubismCore(): Promise<void> {
  if ('Live2DCubismCore' in globalThis) return Promise.resolve()
  loading ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = CORE_URL
    script.onload = () => resolve()
    script.onerror = () => {
      loading = undefined
      script.remove()
      reject(new Error(`Cubism Core is missing (${CORE_URL}): see mika/frontend/README.md`))
    }
    document.head.append(script)
  })
  return loading
}
