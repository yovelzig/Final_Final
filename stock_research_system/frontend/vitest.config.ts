import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
    css: false,
    env: {
      NEXT_PUBLIC_FINQUEST_API_BASE_URL: "http://localhost:8080",
      NEXT_PUBLIC_APP_NAME: "FinQuest",
      FINQUEST_WEB_ORIGIN: "http://localhost:3000",
    },
    include: ["tests/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["app/**", "components/**", "lib/**", "hooks/**", "providers/**"],
    },
  },
});
