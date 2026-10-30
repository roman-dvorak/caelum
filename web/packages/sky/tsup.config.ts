import { defineConfig } from 'tsup'

// ESM only, with the catalog and ephemeris kept as lazily imported chunks.
export default defineConfig({
  entry: { index: 'src/index.ts', react: 'src/react.ts' },
  format: ['esm'],
  dts: { compilerOptions: { ignoreDeprecations: '6.0' } },
  clean: true,
  splitting: true,
  external: ['react', 'astronomy-engine'],
})
