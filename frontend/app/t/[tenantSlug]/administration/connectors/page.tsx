import { redirect } from "next/navigation";
import { primaryConnectorsPath } from "@/lib/tenant-navigation";

export default async function Page({ params }: { params: Promise<{ tenantSlug: string }> }) {
  const { tenantSlug } = await params;
  redirect(primaryConnectorsPath(tenantSlug));
}
