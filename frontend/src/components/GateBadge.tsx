import type { ReadinessGate } from "@/types/astronaut";

const TEXT: Record<ReadinessGate, string> = {
  GO: "text-go",
  CAUTION: "text-caution",
  HOLD: "text-hold",
};
const SOFT_BG: Record<ReadinessGate, string> = {
  GO: "bg-go-bg",
  CAUTION: "bg-caution-bg",
  HOLD: "bg-hold-bg",
};

export default function GateBadge({
  gate,
  tone = "soft",
  className = "",
}: {
  gate: ReadinessGate;
  tone?: "soft" | "white";
  className?: string;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full px-3 py-[5px] text-[11px] font-semibold leading-[1.3] tracking-[0.22px] ${
        tone === "white" ? "bg-white" : SOFT_BG[gate]
      } ${TEXT[gate]} ${className}`}
    >
      <span aria-hidden className="size-2 rounded-full bg-current" />
      {gate}
    </span>
  );
}
