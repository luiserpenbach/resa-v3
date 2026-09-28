// App-level state: user settings, toasts, catalog cache.
import { create } from "zustand";
import { Catalog, calc } from "./api";

type Theme = "light" | "dark" | "system";

function readLS(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writeLS(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked */ }
}

export function applyTheme(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

interface Settings {
  author: string;
  theme: Theme;
  setAuthor(a: string): void;
  setTheme(t: Theme): void;
}

export const useSettings = create<Settings>((set) => ({
  author: readLS("resa.author", ""),
  theme: readLS("resa.theme", "dark") as Theme,
  setAuthor: (author) => { writeLS("resa.author", author); set({ author }); },
  setTheme: (theme) => { writeLS("resa.theme", theme); applyTheme(theme); set({ theme }); },
}));

export const authorName = () => useSettings.getState().author.trim() || "anonymous";

interface Toast { id: number; text: string; tone: "info" | "bad" }
interface Toasts { items: Toast[]; push(text: string, tone?: "info" | "bad"): void }
let seq = 0;
export const useToasts = create<Toasts>((set) => ({
  items: [],
  push: (text, tone = "info") => {
    const id = ++seq;
    set((s) => ({ items: [...s.items, { id, text, tone }] }));
    setTimeout(() => set((s) => ({ items: s.items.filter((t) => t.id !== id) })), tone === "bad" ? 6000 : 3200);
  },
}));
export const toast = (text: string, tone: "info" | "bad" = "info") => useToasts.getState().push(text, tone);

interface CatalogState { catalog: Catalog | null; error: string | null; load(): Promise<void> }
export const useCatalog = create<CatalogState>((set, get) => ({
  catalog: null,
  error: null,
  load: async () => {
    if (get().catalog) return;
    try { set({ catalog: await calc.catalog(), error: null }); }
    catch (e) { set({ error: (e as Error).message }); }
  },
}));

// Recently opened designs (per browser) for the home screen.
export interface Recent { pid: string; did: string; name: string; project: string; at: string }
export function readRecents(): Recent[] {
  try { return JSON.parse(readLS("resa.recent", "[]")) as Recent[]; } catch { return []; }
}
export function pushRecent(r: Omit<Recent, "at">) {
  const list = readRecents().filter((x) => !(x.pid === r.pid && x.did === r.did));
  list.unshift({ ...r, at: new Date().toISOString() });
  writeLS("resa.recent", JSON.stringify(list.slice(0, 6)));
}
