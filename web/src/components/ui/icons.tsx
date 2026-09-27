// Stroke icon set (24px grid, drawn to match the drafting-line aesthetic).
const PATHS: Record<string, string> = {
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14M13 6l6 6-6 6",
  back: "M19 12H5M11 6l-6 6 6 6",
  chevron: "M9 6l6 6-6 6",
  down: "M6 9l6 6 6-6",
  check: "M5 12.5l4.5 4.5L19 7",
  close: "M6 6l12 12M18 6L6 18",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
  save: "M5 3h11l3 3v15H5zM8 3v6h8V3M8 21v-7h8v7",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  warn: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  flame: "M12 22c4 0 7-2.8 7-7 0-4.5-4-7-4-11-3 2-4 4.5-4 7-1-1-2-2-2.5-4C6 9 5 11.5 5 15c0 4.2 3 7 7 7z",
  drop: "M12 2.7l5.7 5.7a8 8 0 1 1-11.3 0z",
  gauge: "M12 21a9 9 0 1 1 9-9M12 12l4-4M3 12h2M12 3v2M19 12h2",
  nozzle: "M4 7h6l3 3.5c1.5 1.8 3 2.5 7 2.5v-2c-4 0-5.5-.7-7-2.5M4 17h6l3-3.5c1.5-1.8 3-2.5 7-2.5",
  channels: "M3 6h18M3 10h18M3 14h18M3 18h18M7 4v16M17 4v16",
  range: "M4 20l5-9 4 5 7-12M4 4v16h16",
  trade: "M4 19V9M10 19V5M16 19v-7M22 19H2",
  report: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h6",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3",
  download: "M12 3v12M7 10l5 5 5-5M4 21h16",
  upload: "M12 21V9M7 14l5-5 5 5M4 3h16",
  star: "M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
  restore: "M3 12a9 9 0 1 0 2.6-6.4L3 8M3 3v5h5",
  play: "M7 4l13 8-13 8z",
  cube: "M12 2l9 5v10l-9 5-9-5V7zM12 22V12M21 7l-9 5-9-5",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  undo: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  redo: "M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3",
  edit: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
  compare: "M9 3v18M15 3v18M3 8h6M15 16h6",
  thermometer: "M14 14.8V4a2 2 0 1 0-4 0v10.8a4 4 0 1 0 4 0z",
};

export function Icon({ name, size, className = "" }: { name: keyof typeof PATHS | string; size?: "sm" | "lg"; className?: string }) {
  const cls = `icon${size ? ` icon-${size}` : ""} ${className}`;
  return (
    <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name] ?? PATHS.info} />
    </svg>
  );
}

/** Brand mark: a bell nozzle contour in section, drawn as two ink strokes. */
export function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="7" fill="var(--ink)" />
      <path d="M6 10.5h7.5l2.2 3.2c1.4 2 3.4 2.3 5.2 1V13c2-2 4.5-3.5 5.6-4.2M6 21.5h7.5l2.2-3.2c1.4-2 3.4-2.3 5.2-1V19c2 2 4.5 3.5 5.6 4.2"
        stroke="var(--surface)" strokeWidth="1.7" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 16h24" stroke="var(--hot)" strokeWidth="1.2" strokeDasharray="3 1.6 1 1.6" />
    </svg>
  );
}
