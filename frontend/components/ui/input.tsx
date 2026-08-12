import * as React from "react";
import { cn } from "@/lib/utils";
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => <input ref={ref} className={cn("h-control w-full rounded-md border border-peka-border-strong bg-peka-surface px-3 text-sm text-peka-text outline-none placeholder:text-peka-muted focus:border-peka-primary focus:ring-2 focus:ring-[var(--peka-focus-ring)] disabled:bg-peka-app disabled:text-peka-muted", className)} {...props} />);
Input.displayName = "Input";
