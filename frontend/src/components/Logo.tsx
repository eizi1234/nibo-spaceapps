export default function Logo({ className = "" }: { className?: string }) {
  return (
    <span
      role="img"
      aria-label="NIBO"
      className={`inline-flex items-end font-extrabold leading-none tracking-[-0.03em] text-white ${className}`}
      style={{ fontSize: 32 }}
    >
      <span>n</span>
      <span className="relative inline-block">
        ı
        <svg
          aria-hidden
          viewBox="0 0 20 20"
          width="16"
          height="16"
          className="absolute block"
          style={{ left: "50%", marginLeft: -8, bottom: "100%", marginBottom: -3 }}
        >
          <defs>
            <mask id="nibo-moon">
              <rect width="20" height="20" fill="#fff" />
              <circle cx="14" cy="6" r="8.2" fill="#000" />
            </mask>
          </defs>
          <circle cx="10" cy="10" r="10" fill="#eaf447" mask="url(#nibo-moon)" />
        </svg>
      </span>
      <span>bo</span>
    </span>
  );
}
