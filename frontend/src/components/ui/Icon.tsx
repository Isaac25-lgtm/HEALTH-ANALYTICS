/**
 * Local outline icons (24×24, 1.8px stroke, currentColor). No icon font, no external request.
 * Every icon is decorative (`aria-hidden`); the adjacent text carries the meaning.
 */
const PATHS = {
  national: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm-9 9h18M12 3c2.5 2.6 3.8 5.6 3.8 9S14.5 18.4 12 21M12 3C9.5 5.6 8.2 8.6 8.2 12S9.5 18.4 12 21",
  regional: "M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5L9 4Zm0 0v13.5m6-11v13.5",
  district: "M4 21V8l8-5 8 5v13M9 21v-6h6v6M8 11h2m4 0h2",
  sub_county: "M4 5h7v6H4zM13 5h7v6h-7zM4 13h7v6H4zM13 13h7v6h-7z",
  facility: "M4 21V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v15M3 21h18M12 8v6m-3-3h6",
  anc: "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 10c.6-4 3.4-6.5 7-6.5s6.4 2.5 7 6.5",
  intrapartum: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z",
  immunization: "m18 2 4 4m-2-2-3.5 3.5M15 5l4 4M13.5 6.5 5 15l-1 5 5-1 8.5-8.5M8 12l4 4M5 15l4 4",
  mpdsr: "M9 4h6v3H9zM7 5.5H5.5V21h13V5.5H17M9 12h6m-6 4h4",
  maps: "M12 21s-6.5-6.2-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21Zm0-8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  trends: "M3 17 9 11l4 4 8-8M15 7h6v6",
  quality: "M12 3 4.5 6v5.5c0 4.6 3.1 8.4 7.5 9.5 4.4-1.1 7.5-4.9 7.5-9.5V6L12 3Zm-3.5 9 2.5 2.5 4.5-5",
  reports: "M12 3v12m0 0-4.5-4.5M12 15l4.5-4.5M4 17v3h16v-3",
  ai: "M12 3v4m0 10v4M3 12h4m10 0h4M6.3 6.3l2.5 2.5m6.4 6.4 2.5 2.5m0-11.4-2.5 2.5m-6.4 6.4-2.5 2.5",
  admin: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.3 7.3 0 0 0-2-1.2L14.5 3h-4l-.4 2.6a7.3 7.3 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.3 7.3 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.3 7.3 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Zm4 4a2 2 0 0 0 4 0",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 4.5 4.5",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4m8-4v4",
  compare: "M7 7h13m0 0-3-3m3 3-3 3M17 17H4m0 0 3-3m-3 3 3 3",
  pin: "M12 21s-6-5.8-6-10.5a6 6 0 0 1 12 0C18 15.2 12 21 12 21Zm0-8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  programme: "M4 6h16M4 12h16M4 18h10",
  indicator: "M5 20V10m7 10V4m7 16v-7",
  scope: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  role: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9c.6-4 3.4-6 7-6s6.4 2 7 6",
  alert: "M12 4 2.5 20h19L12 4Zm0 6v4.5m0 2.5v.5",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v6m0-9v.5",
  up: "M12 19V5m0 0-5 5m5-5 5 5",
  down: "M12 5v14m0 0-5-5m5 5 5-5",
  flat: "M5 12h14",
  idea: "M9 18h6m-5 3h4M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3Z",
  table: "M4 5h16v14H4zM4 10h16M10 10v9",
  chart: "M4 20V4m0 16h16M8 16v-5m4 5V8m4 8v-3",
  file: "M6 3h8l4 4v14H6zM14 3v4h4",
  sheet: "M6 3h8l4 4v14H6zM14 3v4h4M9 12l6 6m0-6-6 6",
  slides: "M6 3h8l4 4v14H6zM14 3v4h4M9 12h3.5a2 2 0 0 1 0 4H9v-4Zm0 4v3",
  download: "M12 4v11m0 0-4-4m4 4 4-4M5 19h14",
  arrow: "M5 12h14m0 0-5-5m5 5-5 5",
  logout: "M15 17l5-5-5-5m5 5H9m4 9H5V3h8",
  chevron: "M6 9l6 6 6-6",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`icon ${className ?? ""}`}
      data-icon={name}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
