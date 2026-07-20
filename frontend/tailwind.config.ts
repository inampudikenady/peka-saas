import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: { colors: { ink: "#18212f", brand: "#2563eb" } } },
  plugins: [],
} satisfies Config;
