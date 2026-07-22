import typography from "@tailwindcss/typography";
import type { Config } from "tailwindcss";

/**
 * FinQuest design tokens. Every color a component uses must come from
 * this palette (via Tailwind utility classes like `bg-surface` or
 * `text-danger`) - never a hard-coded hex value in a component.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#F7F8FB",
        surface: "#FFFFFF",
        primary: {
          DEFAULT: "#2D5BFF",
          hover: "#1E44D6",
          light: "#E8EDFF",
        },
        secondary: {
          DEFAULT: "#0FA36B",
          light: "#E3F7EE",
        },
        success: {
          DEFAULT: "#1A9E5A",
          light: "#E3F7EE",
        },
        warning: {
          DEFAULT: "#B76E00",
          light: "#FFF3DF",
        },
        danger: {
          DEFAULT: "#D8342A",
          light: "#FDEAE9",
        },
        muted: "#6B7280",
        border: "#E3E6EE",
        "focus-ring": "#2D5BFF",
      },
      borderRadius: {
        card: "1rem",
      },
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.2s ease-out",
      },
    },
  },
  plugins: [typography],
};

export default config;
