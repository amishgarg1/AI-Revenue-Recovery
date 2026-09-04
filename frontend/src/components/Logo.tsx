/**
 * The RecoverOS mark.
 *
 * Same geometry as `app/icon.svg` — the product's own chart reduced to a
 * glyph: the wedge between a flat control arm and a treated one rising away
 * from it. That gap is the lift.
 *
 * Kept in sync by hand rather than shared, because the favicon has to be a
 * standalone file for Next's icon convention to pick it up.
 */
export default function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      className="shrink-0"
    >
      <defs>
        <linearGradient id="recoveros-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#3d8ae8" />
          <stop offset="100%" stopColor="#159c6c" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="7.5" fill="url(#recoveros-mark)" />
      <path
        d="M6.5 22.8 L13 19.8 L18.2 13 L25.5 6.6 L25.5 21.4 Z"
        fill="#ffffff"
        fillOpacity={0.92}
      />
      <path
        d="M6.5 22.8 L13 19.8 L18.2 13 L25.5 6.6"
        stroke="#ffffff"
        strokeWidth={2.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}
