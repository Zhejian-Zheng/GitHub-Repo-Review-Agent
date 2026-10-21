import React from "react";
const badgeStyles = {
  critical: "bg-red-100 text-red-800 ring-red-200",
  high: "bg-red-100 text-red-800 ring-red-200",
  medium: "bg-amber-100 text-amber-800 ring-amber-200",
  low: "bg-sky-100 text-sky-800 ring-sky-200",
  info: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  neutral: "bg-stone-100 text-stone-700 ring-stone-200",
  success: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-100 text-amber-800 ring-amber-200",
  error: "bg-red-100 text-red-800 ring-red-200"
};

export function Badge({ tone = "neutral", children }) {
  return (
    <span
      className={`inline-flex min-h-7 items-center rounded-full px-2.5 py-1 text-xs font-bold ring-1 ${
        badgeStyles[tone] ?? badgeStyles.neutral
      }`}
    >
      {children}
    </span>
  );
}

export function formatDate(value) {
  if (!value) return "just now";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export const importantSeverity = new Set(["critical", "high", "medium"]);
