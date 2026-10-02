import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    coverage: {
      provider: 'v8',
      include: [
        'src/App.tsx',
        'src/components/HistoryPanel.tsx',
        'src/components/PublicationNotice.tsx',
        'src/data/api.ts',
        'src/data/publication.ts',
        'src/domain/coverage.ts',
        'src/domain/history.ts',
        'src/domain/strategyPresentation.ts',
      ],
      exclude: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
      reporter: ['text', 'json-summary'],
      thresholds: { lines: 80, perFile: true },
    },
  },
})
