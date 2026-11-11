import type { ReactNode } from "react";

/** One small drawing per idea, on a 48 × 48 grid; named after the page it stands for. */
const art: Record<string, ReactNode> = {
  instruments: (
    <>
      <rect
        x="8"
        y="10"
        width="32"
        height="28"
        rx="3"
        fill="var(--surface-1)"
      />
      <path d="M8 17h32M24 24v5" />
      <rect x="20" y="14" width="8" height="10" rx="1.5" fill="var(--brand)" />
      <rect x="12" y="31" width="7" height="4" rx="1" fill="var(--accent)" />
      <rect x="21" y="31" width="7" height="4" rx="1" fill="var(--info)" />
      <rect x="30" y="31" width="7" height="4" rx="1" fill="var(--warn)" />
    </>
  ),
  learn: (
    <>
      <path d="M8 39h32V18h-8v7h-8v7h-8v7z" fill="var(--surface-1)" />
      <path d="M36 18V7" />
      <path d="M36 7l-9 3.5 9 3.5z" fill="var(--accent)" />
    </>
  ),
  sim: (
    <>
      <rect
        x="7"
        y="10"
        width="34"
        height="23"
        rx="3"
        fill="var(--surface-1)"
      />
      <path d="M21 16l9 5.5-9 5.5z" fill="var(--accent)" />
      <path d="M17 39h14M24 33v6" />
    </>
  ),
  marketplace: (
    <>
      <rect x="7" y="8" width="13" height="9" rx="2" fill="var(--info)" />
      <rect x="7" y="30" width="13" height="9" rx="2" fill="var(--brand)" />
      <path d="M13.5 17v13M20 34.5h6" />
      <path d="M29 31l10-10 3 3-10 10-4 1z" fill="var(--warn)" />
    </>
  ),
  groups: (
    <>
      <path
        d="M10 9h16a4 4 0 014 4v8a4 4 0 01-4 4h-8l-6 5v-5h-2a4 4 0 01-4-4v-8a4 4 0 014-4z"
        fill="var(--surface-1)"
      />
      <path
        d="M24 21h14a4 4 0 014 4v6a4 4 0 01-4 4h-1v4l-5-4h-8a4 4 0 01-4-4v-6a4 4 0 014-4z"
        fill="var(--accent)"
      />
      <path d="M12 15h12M12 19h7" />
    </>
  ),
  onboard: (
    <>
      <path d="M22 12l14 7v15l-14 7-14-7V19z" fill="var(--surface-1)" />
      <path d="M8 19l14 7 14-7M22 26v15" />
      <circle cx="37" cy="12" r="7" fill="var(--accent)" />
      <path d="M37 8.5v7M33.5 12h7" stroke="var(--on-brand)" />
    </>
  ),
  twin: (
    <>
      <rect x="5" y="13" width="15" height="22" rx="2.5" fill="var(--brand)" />
      <rect
        x="28"
        y="13"
        width="15"
        height="22"
        rx="2.5"
        fill="var(--surface-1)"
        strokeDasharray="3 2.5"
      />
      <path d="M21.5 20h5M26.5 28h-5" />
    </>
  ),
  plan: (
    <>
      <rect
        x="6"
        y="10"
        width="36"
        height="28"
        rx="3"
        fill="var(--surface-1)"
      />
      <rect x="10" y="14" width="11" height="8" rx="1.5" fill="var(--info)" />
      <rect x="29" y="26" width="9" height="8" rx="1.5" fill="var(--warn)" />
      <path d="M15 31l10-8 6 3" />
      <circle cx="15" cy="31" r="3.2" fill="var(--brand)" />
    </>
  ),
  readiness: (
    <>
      <rect
        x="11"
        y="9"
        width="26"
        height="31"
        rx="3"
        fill="var(--surface-1)"
      />
      <rect x="18" y="6" width="12" height="6" rx="2" fill="var(--brand)" />
      <path d="M27 21h6M27 31h6" />
      <path
        d="M16 20.5l2.5 2.5 4.5-5M16 30.5l2.5 2.5 4.5-5"
        stroke="var(--ok)"
        strokeWidth="2.2"
      />
    </>
  ),
  runs: (
    <>
      <circle cx="24" cy="24" r="14" fill="var(--surface-1)" stroke="none" />
      <path d="M11.5 20A13 13 0 1 1 13 31" />
      <path d="M10 12v8h8" />
      <path d="M21 18.5l8.5 5.5-8.5 5.5z" fill="var(--accent)" />
    </>
  ),
  compare: (
    <>
      <rect
        x="6"
        y="10"
        width="15"
        height="28"
        rx="2.5"
        fill="var(--surface-1)"
      />
      <rect
        x="27"
        y="10"
        width="15"
        height="28"
        rx="2.5"
        fill="var(--surface-1)"
      />
      <path d="M10 17h7M10 23h7M31 17h7M31 23h7" />
      <path d="M10 30h7" stroke="var(--ok)" strokeWidth="2.6" />
      <path d="M31 30h7" stroke="var(--accent)" strokeWidth="2.6" />
    </>
  ),
  caught: (
    <>
      <path d="M24 7l18 32H6z" fill="var(--warn)" />
      <path d="M24 19v9" strokeWidth="2.6" />
      <circle cx="24" cy="33.5" r="1.6" fill="var(--ink)" stroke="none" />
    </>
  ),
  agreed: (
    <>
      <circle cx="24" cy="24" r="16" fill="var(--ok)" />
      <path
        d="M16 24.5l5.5 5.5L33 18"
        stroke="var(--on-brand)"
        strokeWidth="3"
      />
    </>
  ),
  samples: (
    <>
      <rect
        x="6"
        y="11"
        width="36"
        height="26"
        rx="3"
        fill="var(--surface-1)"
      />
      <circle cx="14" cy="19" r="3" fill="var(--info)" />
      <circle cx="24" cy="19" r="3" fill="var(--accent)" />
      <circle cx="34" cy="19" r="3" fill="var(--warn)" />
      <circle cx="14" cy="29" r="3" fill="var(--brand)" />
      <circle cx="24" cy="29" r="3" />
      <circle cx="34" cy="29" r="3" />
    </>
  ),
  measure: (
    <>
      <path d="M8 8v32h32" />
      <rect x="13" y="26" width="6" height="14" fill="var(--info)" />
      <rect x="22" y="18" width="6" height="22" fill="var(--brand)" />
      <rect x="31" y="11" width="6" height="29" fill="var(--accent)" />
    </>
  ),
  decide: (
    <>
      <path d="M24 41V27M24 27C24 19 14 20 13 11M24 27c0-8 10-7 11-16" />
      <path d="M8 15l5-5 5 5M30 15l5-5 5 5" />
      <circle cx="24" cy="41" r="3" fill="var(--brand)" />
    </>
  ),
};

export default function Pictogram({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      {art[name]}
    </svg>
  );
}
