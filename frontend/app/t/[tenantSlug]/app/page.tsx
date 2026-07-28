import { redirect } from "next/navigation";

export default async function TenantApplicationRedirect({
  params,
}: {
  params: Promise<{ tenantSlug: string }>;
}) {
  const { tenantSlug } = await params;
  redirect(`/t/${tenantSlug}/ai`);
}
