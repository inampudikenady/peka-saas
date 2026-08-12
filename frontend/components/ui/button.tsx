import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const variants = cva("inline-flex h-control items-center justify-center rounded-md px-4 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--peka-focus-ring)] disabled:pointer-events-none disabled:opacity-50", { variants: { variant: { default: "bg-peka-primary text-white hover:bg-peka-primary-hover", outline: "border border-peka-border-strong bg-peka-surface hover:bg-peka-app", ghost: "hover:bg-peka-primary-subtle", danger: "bg-peka-danger text-white hover:opacity-90", destructive: "bg-peka-danger text-white hover:opacity-90" } }, defaultVariants: { variant: "default" } });
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> { asChild?: boolean }
export function Button({ className, variant, asChild, ...props }: ButtonProps) { const Comp = asChild ? Slot : "button"; return <Comp className={cn(variants({ variant }), className)} {...props} />; }
