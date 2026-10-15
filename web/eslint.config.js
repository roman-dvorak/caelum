import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// Shared flat config reused by every package/app in the workspace (see the
// local eslint.config.js next to this one in each apps/* and packages/*
// project, which import and re-export this array). Keeping it here avoids
// drift between local-web, remote-web, ui and api-client's lint rules.
export default defineConfig([
  globalIgnores(['**/dist/**', '**/node_modules/**', '**/.tmp/**']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
])
