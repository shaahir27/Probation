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
        surfaceRecessed: "var(--surface-recessed)",
        "surface-recessed": "var(--surface-recessed)",
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
          muted: "var(--brand-muted)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          on: "var(--on-accent)",
          soft: "var(--accent-soft)",
        },
        focus: "var(--focus)",
        status: {
          success: "var(--success)",
          warning: "var(--warning)",
          danger: "var(--danger)",
        },
      },
      fontFamily: {
        serif: [
          "Fraunces",
          "Georgia",
          "Cambria",
          '"Times New Roman"',
          "Times",
          "serif",
        ],
        sans: [
          "Manrope",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
