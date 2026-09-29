/** The Kyron "C with a dot" mark, drawn as SVG so it stays crisp at small sizes. */
export function KyronMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path d="M27.3 10.5A12.5 12.5 0 1 0 27.3 21.5" fill="none" stroke="currentColor" strokeWidth="4" />
      <circle cx="16" cy="16" r="3.4" fill="currentColor" />
    </svg>
  );
}

export function KyronWordmark() {
  return (
    <>
      <KyronMark />
      <span>Kyron</span>
    </>
  );
}
