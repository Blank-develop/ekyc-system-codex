import { useSyncExternalStore } from "react";

export type Lang = "lo" | "en";

const STORAGE_KEY = "kyron.lang";
const listeners = new Set<() => void>();

function readStoredLang(): Lang {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "lo" || stored === "en") return stored;
  } catch {
    // Storage can be blocked (private mode); fall back to Lao.
  }
  return "lo";
}

let current: Lang = readStoredLang();
document.documentElement.lang = current;

/** Pick the Lao or English text for the active language. */
export function L(lo: string, en: string) {
  return current === "en" ? en : lo;
}

export function getLang() {
  return current;
}

export function setLang(lang: Lang) {
  if (lang === current) return;
  current = lang;
  document.documentElement.lang = lang;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Non-fatal: the choice just won't persist across reloads.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-render the calling component whenever the language changes. */
export function useLang() {
  return useSyncExternalStore(subscribe, getLang);
}
