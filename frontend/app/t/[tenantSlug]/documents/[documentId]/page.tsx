import { redirect } from "next/navigation";

export default async function LegacyDocumentDetailRedirect({
  params,
}: {
  params: Promise<{ tenantSlug: string; documentId: string }>;
}) {
  const { tenantSlug } = await params;
  redirect(`/t/${tenantSlug}/connectors`);
}
