import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

/** Kennzeichnet Knöpfe, die das Sprachmodell arbeiten lassen. */
export function AiIcon({ className }: { className?: string }) {
  return (
    <Sparkles
      className={cn("size-4 text-violet-500 dark:text-violet-300", className)}
      aria-hidden="true"
      data-ai=""
    />
  );
}
