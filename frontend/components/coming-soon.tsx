import { Card } from "@/components/ui/card";
export function ComingSoon({ title, description }: { title: string; description: string }) { return <Card className="p-8"><h2 className="text-xl font-semibold">{title}</h2><p className="mt-2 text-sm text-peka-secondary">{description}</p><p className="mt-4 text-xs font-medium uppercase tracking-wide text-peka-muted">Coming soon</p></Card>; }
