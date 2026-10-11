// Puts Mika's Live2D model together in public/models/miku/ (git-ignored), for the dev server:
// - the runtime files of Live2D's sample model, from others/2D/miku_pro/runtime (not in git: Live2D's license);
// - Mika's expressions, from live2d/expressions (in git), registered under FileReferences.Expressions.
// `npm run dev` runs it first; after editing an expression, run `npm run model` and reload the page.
import { cpSync, existsSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..')
const runtime = join(frontend, '..', '..', 'others', '2D', 'miku_pro', 'runtime')
const expressions = join(frontend, 'live2d', 'expressions')
const target = join(frontend, 'public', 'models', 'miku')
const core = join(frontend, 'public', 'live2dcubismcore.min.js')
const MODEL = 'miku_sample_t04.model3.json'

function fail(message) {
  console.error(message)
  process.exit(1)
}

if (!existsSync(join(runtime, MODEL))) {
  fail(`The Live2D model is missing: copy its runtime folder to ${relative(process.cwd(), runtime)}`)
}

const files = readdirSync(expressions).filter((file) => file.endsWith('.exp3.json')).sort()
const model = JSON.parse(readFileSync(join(runtime, MODEL), 'utf8'))
model.FileReferences.Expressions = files.map((file) => ({
  Name: basename(file, '.exp3.json'), // an emotion, as the avatar page receives it
  File: `expressions/${file}`,
}))
// Mika blinks through src/live2d/blink.ts. easy-live2d only runs Cubism's own eye blink in the frames between two
// idle motions, where it reopens the eyes an expression has narrowed, so the model loses its EyeBlink group.
model.Groups = model.Groups.filter((group) => group.Name !== 'EyeBlink')

rmSync(target, { recursive: true, force: true })
cpSync(runtime, target, { recursive: true })
cpSync(expressions, join(target, 'expressions'), { recursive: true })
writeFileSync(join(target, MODEL), JSON.stringify(model, null, '\t') + '\n')
console.log(`Live2D model ready in public/models/miku, with expressions: ${files.map((f) => basename(f, '.exp3.json')).join(', ')}`)

if (!existsSync(core)) {
  fail(
    'Cubism Core is missing: download the Cubism SDK for Web R5 from https://www.live2d.com/en/sdk/download/web/ ' +
      `and copy Core/live2dcubismcore.min.js to ${relative(process.cwd(), core)}`,
  )
}
