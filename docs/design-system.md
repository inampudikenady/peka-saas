# PEKA design tokens

PEKA SaaS is the visual baseline for the product. Its semantic token contract lives in
`frontend/app/peka-tokens.css` and is mapped into Tailwind by
`frontend/tailwind.config.ts`. Platform administrator, platform read-only, tenant
administrator, and tenant user experiences all use the same `AppShell` and tokenized
primitives; permissions control available actions, not visual identity.

The Connector is currently a separate build and cannot import the SaaS component
package. It therefore carries a deliberately matching copy of the CSS token contract
in `peka-connector/frontend/src/peka-tokens.css`, with an MUI adapter in
`peka-connector/frontend/src/pekaTheme.ts`. This duplication is temporary until the
repositories adopt a versioned shared UI package. Token names and values must remain
identical between the builds in the meantime.

New UI code should use semantic tokens or shared primitives rather than literal colors.
Status colors are reserved for status meaning; primary blue is used for actions and
selection.
