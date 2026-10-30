import { Badge } from "@/components/ui/badge";

export function StatusBadge({
  ok,
  okLabel,
  failLabel,
}: {
  ok: boolean;
  okLabel: string;
  failLabel: string;
}) {
  return (
    <Badge tone={ok ? "success" : "danger"}>
      <span
        aria-hidden="true"
        className={
          ok ? "size-1.5 rounded-full bg-emerald-500" : "size-1.5 rounded-full bg-rose-500"
        }
      />
      {ok ? okLabel : failLabel}
    </Badge>
  );
}
