/**
 * Version and build stamped into the web apps (`define` in each app's
 * vite.config.ts; read back by `BUILD_INFO` in @caelum/ui). The version is
 * the Python package's — the local UI ships inside that same wheel — and
 * the build is the commit plus the date it was built.
 */
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

function packageVersion(): string {
  const pyproject = readFileSync(fileURLToPath(new URL('../pyproject.toml', import.meta.url)), 'utf8')
  return /^version\s*=\s*"([^"]+)"/m.exec(pyproject)?.[1] ?? 'dev'
}

function commit(): string {
  try {
    const sha = execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
    const dirty = execSync('git status --porcelain', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
    return dirty ? `${sha}+dirty` : sha
  } catch {
    return 'unknown'
  }
}

export function buildInfoDefines(): Record<string, string> {
  return {
    __CAELUM_VERSION__: JSON.stringify(packageVersion()),
    __CAELUM_BUILD__: JSON.stringify(`${commit()} · ${new Date().toISOString().slice(0, 10)}`),
  }
}
