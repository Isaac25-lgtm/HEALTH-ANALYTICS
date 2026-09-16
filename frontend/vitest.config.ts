import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    // The gate integration tests inventory system processes. Running other test files in parallel
    // can create unrelated Vitest workers after that baseline in restricted Windows fallback mode.
    fileParallelism: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/test/**/*.test.ts", "src/test/**/*.test.tsx", "scripts/**/*.test.mjs"],
  },
});
