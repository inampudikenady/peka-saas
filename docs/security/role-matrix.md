# Connector role matrix

| Capability | Platform Admin | Platform Read Only | Tenant Admin | Tenant User (read only) | Connector |
|---|---:|---:|---:|---:|---:|
| View all connector inventory/details | Yes | Yes | No | No | No |
| Launch tenant portal | Existing authorized flow | Existing authorized flow | N/A | N/A | No |
| View own-tenant connectors/details/tokens | No impersonation | No impersonation | Yes | Yes | No |
| Generate/revoke registration token | No | No | Yes | No | No |
| Retire connector | No | No | Yes | No | No |
| Register with one-time token | No | No | No | No | Yes |
| Send authenticated heartbeat | No | No | No | No | Yes |
| Read any connector secret/hash | No | No | No | No | No |

## Status interpretation for every role

All roles see the same SaaS-derived connector status. Healthy source counts indicate successful local readability/scanning only. They do not establish that documents exist in SaaS.

`Connected`, `Degraded`, `Out of Sync`, `Disconnected`, `Authentication Failed`, and `Retired` are currently presented. `In Sync` is reserved and hidden until data synchronization exists.

> Connected means the connector is communicating with PEKA SaaS. It does not mean source data has been uploaded or synchronized.
