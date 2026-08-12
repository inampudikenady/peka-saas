import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: {
    colors: {
      ink: "var(--peka-text-primary)", brand: "var(--peka-primary)",
      "peka-app": "var(--peka-bg-app)", "peka-surface": "var(--peka-bg-surface)",
      "peka-sidebar": "var(--peka-bg-sidebar)", "peka-sidebar-hover": "var(--peka-bg-sidebar-hover)",
      "peka-sidebar-active": "var(--peka-bg-sidebar-active)",
      "peka-primary": "var(--peka-primary)", "peka-primary-hover": "var(--peka-primary-hover)",
      "peka-primary-subtle": "var(--peka-primary-subtle)",
      "peka-text": "var(--peka-text-primary)", "peka-secondary": "var(--peka-text-secondary)",
      "peka-muted": "var(--peka-text-muted)", "peka-on-dark": "var(--peka-text-on-dark)",
      "peka-border": "var(--peka-border-default)", "peka-border-strong": "var(--peka-border-strong)",
      "peka-success": "var(--peka-success)", "peka-success-subtle": "var(--peka-success-subtle)",
      "peka-warning": "var(--peka-warning)", "peka-warning-subtle": "var(--peka-warning-subtle)",
      "peka-danger": "var(--peka-danger)", "peka-danger-subtle": "var(--peka-danger-subtle)",
      "peka-info": "var(--peka-info)", "peka-info-subtle": "var(--peka-info-subtle)",
    },
    fontFamily: { sans: ["var(--peka-font-sans)"] },
    borderRadius: { peka: "var(--peka-radius-card)" },
    boxShadow: { peka: "var(--peka-shadow-card)" },
    height: { header: "var(--peka-header-height)", control: "var(--peka-control-height)" },
    width: { sidebar: "var(--peka-sidebar-width)", "sidebar-wide": "var(--peka-sidebar-wide-width)" },
  } },
  plugins: [],
} satisfies Config;
