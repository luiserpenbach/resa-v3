import { useEffect, useState } from "react";
import { Link, Route, Switch } from "wouter";
import { Dialog, Menu, Toasts } from "./components/ui/display";
import { Field, Segmented } from "./components/ui/controls";
import { BrandMark, Icon } from "./components/ui/icons";
import { useCatalog, useSettings } from "./lib/stores";
import Home from "./pages/Home";
import ProjectPage from "./pages/ProjectPage";
import DesignPage from "./pages/DesignPage";
import { EstimatePage } from "./pages/EstimatePage";

export default function App() {
  const load = useCatalog((s) => s.load);
  useEffect(() => { void load(); }, [load]);
  return (
    <div className="app">
      <Switch>
        <Route path="/" component={Home} />
        <Route path="/estimate" component={EstimatePage} />
        <Route path="/estimate/:section" component={EstimatePage} />
        <Route path="/p/:pid" component={ProjectPage} />
        <Route path="/p/:pid/d/:did" component={DesignPage} />
        <Route path="/p/:pid/d/:did/:section" component={DesignPage} />
        <Route><TopBar /><div className="page"><h1 className="display">Page not found</h1><p><Link href="/">Back to the workspace</Link></p></div></Route>
      </Switch>
      <Toasts />
    </div>
  );
}

export function TopBar({ crumbs = [], children }: { crumbs?: { label: string; href?: string }[]; children?: React.ReactNode }) {
  const [settings, setSettings] = useState(false);
  const { theme, setTheme } = useSettings();
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  return (
    <header className="topbar">
      <Link href="/" className="brand" aria-label="RESA Studio home">
        <span className="brand-mark"><BrandMark /></span>
        <span className="brand-name">RESA<em>Studio</em></span>
      </Link>
      {crumbs.length > 0 && (
        <nav className="crumbs" aria-label="Breadcrumb">
          {crumbs.map((c, i) => (
            <span key={i} className="row" style={{ gap: 6, minWidth: 0 }}>
              <span className="sep">/</span>
              {c.href ? <Link href={c.href}>{c.label}</Link> : <span className="current">{c.label}</span>}
            </span>
          ))}
        </nav>
      )}
      <span className="topbar-spacer" />
      <div className="topbar-actions">
        {children}
        <button className="btn btn-ghost btn-icon" title={dark ? "Light theme" : "Dark theme"} aria-label="Toggle theme"
          onClick={() => setTheme(dark ? "light" : "dark")}>
          <Icon name={dark ? "sun" : "moon"} />
        </button>
        <Menu trigger={(open) => <button className="btn btn-ghost btn-icon" aria-label="Settings" onClick={open}><Icon name="gear" /></button>}
          items={[
            { label: "Your name & preferences", icon: "edit", onClick: () => setSettings(true) },
            { label: "Classic Studio (previous UI)", icon: "back", onClick: () => { window.location.href = "/classic/"; } },
          ]} />
      </div>
      {settings && <SettingsDialog theme={theme} setTheme={setTheme} onClose={() => setSettings(false)} />}
    </header>
  );
}

function SettingsDialog({ onClose, theme, setTheme }: { onClose(): void; theme: string; setTheme(t: "light" | "dark" | "system"): void }) {
  const { author, setAuthor } = useSettings();
  const [name, setName] = useState(author);
  return (
    <Dialog title="Preferences" sub="Stored in this browser." onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={() => { setAuthor(name.trim()); onClose(); }}>Save</button></>}>
      <Field label="Your name" hint="Shown on the versions you save, so your team knows who changed what.">
        <input className="plain-input" value={name} autoFocus onChange={(e) => setName(e.target.value)} placeholder="e.g. Ada Lovelace" />
      </Field>
      <Field label="Appearance">
        <Segmented value={theme} onChange={(v) => setTheme(v as "light" | "dark" | "system")}
          options={[{ value: "system", label: "Match system" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
      </Field>
    </Dialog>
  );
}
