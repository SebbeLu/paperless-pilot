import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const bytesFormat = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

export function formatBytes(bytes: number): string {
  if (bytes < 1e9) {
    return `${bytesFormat.format(bytes / 1e6)} MB`;
  }
  return `${bytesFormat.format(bytes / 1e9)} GB`;
}
