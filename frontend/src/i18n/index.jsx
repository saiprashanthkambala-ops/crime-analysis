import React, { createContext, useContext, useEffect, useState, useMemo } from 'react'
import en from './locales/en'
import te from './locales/te'
import hi from './locales/hi'
import ta from './locales/ta'

const LANGUAGE_STORAGE_KEY = 'crime_analysis_language'

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'EN', name: 'English' },
  { code: 'te', label: 'తెలుగు', name: 'Telugu' },
  { code: 'hi', label: 'हिन्दी', name: 'Hindi' },
  { code: 'ta', label: 'தமிழ்', name: 'Tamil' },
]

const translations = { en, te, hi, ta }

const I18nContext = createContext({
  language: 'en',
  setLanguage: () => {},
  t: (key) => key,
  languages: SUPPORTED_LANGUAGES,
})

export function I18nProvider({ children }) {
  const [language, setLanguageState] = useState(() => {
    try {
      const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY)
      if (saved && translations[saved]) return saved
    } catch {
      // localStorage may be inaccessible
    }
    return 'en'
  })

  useEffect(() => {
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
    } catch {
      // ignore
    }
  }, [language])

  const setLanguage = (lang) => {
    if (translations[lang]) {
      setLanguageState(lang)
    }
  }

  const t = useMemo(() => {
    const currentDict = translations[language] || translations.en
    const fallbackDict = translations.en

    return (key, params) => {
      let str = currentDict[key] ?? fallbackDict[key] ?? key
      if (typeof str !== 'string') return str

      if (params && typeof params === 'object') {
        Object.entries(params).forEach(([k, v]) => {
          str = str.replaceAll(`{${k}}`, v != null ? String(v) : '')
        })
      }
      return str
    }
  }, [language])

  const value = useMemo(() => ({
    language,
    setLanguage,
    t,
    languages: SUPPORTED_LANGUAGES,
  }), [language, t])

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  )
}

export function useI18n() {
  return useContext(I18nContext)
}
