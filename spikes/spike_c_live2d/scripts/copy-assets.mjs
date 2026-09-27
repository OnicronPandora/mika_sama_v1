// Copies the git-ignored local assets this spike needs into public/.
// Cubism Core is not copied: each developer downloads it under Live2D's license (see spikes/README.md).
import { cpSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = join(here, '..', '..', '..')
const publicDir = join(here, '..', 'public')

cpSync(join(repoRoot, 'others', '2D', 'miku_pro', 'runtime'), join(publicDir, 'models', 'miku'), { recursive: true })
console.log('Copied Live2D model to public/models/miku')

const ttsOut = join(repoRoot, 'spikes', 'spike_b_tts', 'out')
if (existsSync(ttsOut)) {
  mkdirSync(join(publicDir, 'samples'), { recursive: true })
  for (const file of readdirSync(ttsOut).filter((f) => f.endsWith('.wav'))) {
    cpSync(join(ttsOut, file), join(publicDir, 'samples', file))
  }
  console.log('Copied Spike B audio to public/samples')
} else {
  console.log('No Spike B audio found; run Spike B first to test lipsync with real speech')
}
