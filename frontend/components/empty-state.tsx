import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) { return <Card className="p-10 text-center"><h3 className="font-medium">{title}</h3><div className="mt-1 text-sm text-slate-500">{children}</div>{action && <div className="mt-5">{action}</div>}</Card>; }
