/**
 * Line illustrations for printer cards. These are generic device drawings in
 * the Fruitstand palette (black line, orange accent) — not product photos.
 * Admins choose the closest illustration per printer.
 */
const stroke = { stroke: "currentColor", strokeWidth: 3, strokeLinejoin: "round" as const, strokeLinecap: "round" as const };

export function PrinterArt({ kind }: { kind: string }) {
  switch (kind) {
    case "mfp":
      return (
        <svg viewBox="0 0 160 140" fill="none" aria-hidden="true">
          <rect x="22" y="18" width="116" height="22" rx="4" {...stroke} fill="var(--surface)" />
          <rect x="16" y="40" width="128" height="62" rx="6" {...stroke} fill="var(--surface)" />
          <rect x="24" y="102" width="112" height="24" rx="4" {...stroke} fill="var(--surface)" />
          <path d="M30 114h100" {...stroke} />
          <rect x="102" y="50" width="30" height="16" rx="2" {...stroke} fill="var(--ink)" />
          <circle cx="110" cy="80" r="3.5" fill="var(--accent)" />
          <path d="M44 62h40" {...stroke} />
          <path d="M50 40l6-10h48l6 10" {...stroke} />
        </svg>
      );
    case "inkjet":
      return (
        <svg viewBox="0 0 160 140" fill="none" aria-hidden="true">
          <path d="M50 46V18h60v28" {...stroke} fill="var(--surface)" />
          <rect x="14" y="46" width="132" height="46" rx="10" {...stroke} fill="var(--surface)" />
          <path d="M34 92v18h92V92" {...stroke} fill="var(--surface)" />
          <path d="M46 102h68" {...stroke} />
          <circle cx="124" cy="62" r="4" fill="var(--accent)" />
          <path d="M28 62h50" {...stroke} />
          <rect x="60" y="26" width="40" height="6" rx="2" fill="var(--accent-soft)" />
        </svg>
      );
    case "label":
      return (
        <svg viewBox="0 0 160 140" fill="none" aria-hidden="true">
          <rect x="34" y="28" width="92" height="72" rx="14" {...stroke} fill="var(--surface)" />
          <path d="M56 100v22h48v-22" {...stroke} fill="var(--surface)" />
          <path d="M64 110h32" {...stroke} />
          <circle cx="80" cy="60" r="14" {...stroke} />
          <circle cx="80" cy="60" r="4" fill="var(--accent)" />
        </svg>
      );
    case "plotter":
      return (
        <svg viewBox="0 0 160 140" fill="none" aria-hidden="true">
          <rect x="8" y="34" width="144" height="34" rx="8" {...stroke} fill="var(--surface)" />
          <path d="M30 68l-8 50M130 68l8 50" {...stroke} />
          <path d="M40 68v30h80V68" {...stroke} fill="var(--surface)" />
          <circle cx="132" cy="51" r="4" fill="var(--accent)" />
          <path d="M22 51h70" {...stroke} />
        </svg>
      );
    case "unknown":
      return (
        <svg viewBox="0 0 160 140" fill="none" aria-hidden="true">
          <rect x="24" y="36" width="112" height="60" rx="8" {...stroke} strokeDasharray="8 7" fill="var(--surface)" />
          <path d="M70 60a10 10 0 1 1 14 9c-3 1.5-4 3.5-4 6" {...stroke} />
          <circle cx="80" cy="84" r="2.5" fill="var(--accent)" />
        </svg>
      );
    default: // laser
      return (
        <svg viewBox="0 0 160 140" fill="none" aria-hidden="true">
          <path d="M40 40V16h80v24" {...stroke} fill="var(--surface)" />
          <rect x="18" y="40" width="124" height="58" rx="6" {...stroke} fill="var(--surface)" />
          <path d="M38 98v24h84V98" {...stroke} fill="var(--surface)" />
          <path d="M48 110h64" {...stroke} />
          <rect x="104" y="52" width="26" height="10" rx="2" fill="var(--ink)" />
          <circle cx="117" cy="78" r="4" fill="var(--accent)" />
          <path d="M32 58h50" {...stroke} />
        </svg>
      );
  }
}
