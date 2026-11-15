import type { ReadinessGate } from "@/types/astronaut";

const STYLES: Record<ReadinessGate, string> = {
  GO: "bg-emerald-100 text-emerald-800",
  CAUTION: "bg-amber-100 text-amber-800",
  HOLD: "bg-red-100 text-red-700",
};

export default function GateBadge({ gate, className = "" }: { gate: ReadinessGate; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${STYLES[gate]} ${className}`}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {gate}
    </span>
  );
}
