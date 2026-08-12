"use client";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function CopyButton({
  value,
  label = "Copy",
  iconOnly = false,
}: {
  value: string;
  label?: string;
  iconOnly?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const Icon = copied ? Check : Copy;

  return (
    <Button
      type="button"
      variant={iconOnly ? "ghost" : "outline"}
      className={iconOnly ? "h-8 w-8 shrink-0 p-0" : undefined}
      aria-label={iconOnly ? label : undefined}
      title={iconOnly ? (copied ? "Copied" : label) : undefined}
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      <Icon aria-hidden="true" className={`${iconOnly ? "" : "mr-2"} h-4 w-4`} />
      {iconOnly ? (
        <span className="sr-only" aria-live="polite">{copied ? "Copied" : label}</span>
      ) : copied ? "Copied" : label}
    </Button>
  );
}
