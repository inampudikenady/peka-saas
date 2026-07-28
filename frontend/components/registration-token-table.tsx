"use client";

import { StatusBadge } from "@/components/status-badge";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { RegistrationToken } from "@/lib/types";

export function RegistrationTokenTable({
  items,
  canRevoke,
  onRevoke,
}: {
  items: RegistrationToken[];
  canRevoke: boolean;
  onRevoke: (token: RegistrationToken) => void;
}) {
  const [showInactive, setShowInactive] = useState(false);
  const visible = showInactive ? items : items.filter((token) => token.status === "active");
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={showInactive} onChange={(event) => setShowInactive(event.target.checked)}/>
        Show inactive tokens
      </label>
      <Card className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b bg-slate-50">
          <tr>
            {["Created", "Expires", "Status", "Actions"].map((heading) => (
              <th className="px-4 py-3" key={heading}>{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((token) => (
            <tr className="border-b" key={token.id}>
              <td className="px-4 py-4">{new Date(token.created_at).toLocaleString()}</td>
              <td className="px-4">{new Date(token.expires_at).toLocaleString()}</td>
              <td className="px-4"><StatusBadge status={token.status}/></td>
              <td className="px-4">
                {canRevoke && token.status === "active"
                  ? <Button variant="danger" onClick={() => onRevoke(token)}>Revoke</Button>
                  : <span className="text-xs text-slate-500">No actions</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!visible.length && <p className="p-5 text-sm text-slate-500">No registration tokens.</p>}
      </Card>
    </div>
  );
}
