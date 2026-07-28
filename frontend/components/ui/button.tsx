import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const variants = cva("inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:pointer-events-none disabled:opacity-50", { variants: { variant: { default: "bg-blue-600 text-white hover:bg-blue-700", outline: "border border-slate-300 bg-white hover:bg-slate-50", ghost: "hover:bg-slate-100", danger: "bg-red-600 text-white hover:bg-red-700", destructive: "bg-red-600 text-white hover:bg-red-700" } }, defaultVariants: { variant: "default" } });
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> { asChild?: boolean }
export function Button({ className, variant, asChild, ...props }: ButtonProps) { const Comp = asChild ? Slot : "button"; return <Comp className={cn(variants({ variant }), className)} {...props} />; }
