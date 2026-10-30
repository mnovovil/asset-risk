import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vitest/config";

const FRONT_ROOT = import.meta.dirname;
const TEST_DIR = path.resolve(FRONT_ROOT, "../../test/front");

/** Tests live in test/front, outside this package, so resolve their dependencies from here. */
function resolveTestDependencies(): Plugin {
  return {
    name: "resolve-test-dependencies",
    enforce: "pre",
    async resolveId(source, importer, options) {
      const isBare = !source.startsWith(".") && !path.isAbsolute(source) && !source.startsWith("@/");
      if (!isBare || !importer?.startsWith(TEST_DIR)) return null;
      return this.resolve(source, path.join(FRONT_ROOT, "index.html"), {
        ...options,
        skipSelf: true,
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), resolveTestDependencies()],
  resolve: {
    alias: { "@": path.join(FRONT_ROOT, "src") },
  },
  server: {
    fs: { allow: [path.resolve(FRONT_ROOT, "../..")] },
    proxy: { "/api": process.env.ASSET_RISK_API ?? "http://127.0.0.1:8000" },
  },
  test: {
    dir: TEST_DIR,
    environment: "jsdom",
    setupFiles: [path.join(TEST_DIR, "setup.ts")],
    restoreMocks: true,
  },
});
