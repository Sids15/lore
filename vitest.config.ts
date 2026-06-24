import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Test config kept separate from the Tauri-tuned vite.config.ts.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
