const TONES = {
  soft: "bg-soft text-brand",
  brand: "bg-brand text-white",
  accent: "bg-accent text-on-accent",
};

export function initials(name: string) {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function Avatar({
  name,
  tone = "soft",
  className = "",
}: {
  name: string;
  tone?: keyof typeof TONES;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={`flex size-11 shrink-0 items-center justify-center rounded-full text-sm font-bold leading-[1.3] ${TONES[tone]} ${className}`}
    >
      {initials(name)}
    </span>
  );
}
