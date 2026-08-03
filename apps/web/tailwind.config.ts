import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef7f2",
          100: "#d6ecdf",
          500: "#1f7a54",
          600: "#186043",
          700: "#124b34",
        },
      },
      fontFamily: {
        sans: ["var(--font-arabic)", "var(--font-latin)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
