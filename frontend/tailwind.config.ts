import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#090d16",
        surface: "#111827",
        surfaceElevated: "#1f2937",
        borderSubtle: "#374151",
        accent: {
          blue: "#38bdf8",
          emerald: "#34d399",
          amber: "#fbbf24",
          rose: "#f43f5e",
        },
      },
    },
  },
  plugins: [],
};

export default config;
