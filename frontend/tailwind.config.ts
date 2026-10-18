import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        surfaceRaised: "var(--surface-raised)",
        surfaceSubtle: "var(--surface-subtle)",
        line: "var(--line)",
        ink: {
          DEFAULT: "var(--ink)",
          secondary: "var(--ink-secondary)",
          tertiary: "var(--ink-tertiary)",
        },
        brand: {
          DEFAULT: "var(--brand)",
          hover: "var(--brand-hover)",
          on: "var(--on-brand)",
        },
        focus: "var(--focus)",
        status: {
          success: "var(--success)",
          warning: "var(--warning)",
          danger: "var(--danger)",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
