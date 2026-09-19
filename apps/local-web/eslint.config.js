import { defineConfig, globalIgnores } from 'eslint/config'
import shared from '../../eslint.config.js'

export default defineConfig([globalIgnores(['dist']), ...shared])
