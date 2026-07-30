import { defineStore } from 'pinia'

import { readToken, writeToken } from '@/api/client'

const THEME_KEY = 'personadock.web.theme'

export type ThemeMode = 'light' | 'dark' | 'system'

function readTheme(): ThemeMode {
  const value = localStorage.getItem(THEME_KEY)
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    token: readToken(),
    theme: readTheme() as ThemeMode,
  }),
  actions: {
    setToken(value: string) {
      this.token = value.trim()
      writeToken(this.token)
    },
    setTheme(value: ThemeMode) {
      this.theme = value
      localStorage.setItem(THEME_KEY, value)
      this.applyTheme()
    },
    applyTheme() {
      const dark =
        this.theme === 'dark' ||
        (this.theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
      document.documentElement.classList.toggle('dark', dark)
    },
  },
})
