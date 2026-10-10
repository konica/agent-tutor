import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { port: 10453, strictPort: true },
  build: {
    rolldownOptions: {
      output: {
        // The pdf.js worker ships as .mjs, which stock nginx serves as application/octet-stream, and browsers refuse a
        // module worker of any other type than JavaScript. As .js it is served right anywhere, and the new name skips
        // the octet-stream copies that browsers and CloudFront cached for a year (/assets/ is immutable).
        assetFileNames: (asset) =>
          asset.names.some((name) => name.endsWith(".mjs")) ? "assets/[name]-[hash].js" : "assets/[name]-[hash][extname]",
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: { include: [/\.module\.css$/, /tokens\.css/], modules: { classNameStrategy: "non-scoped" } },
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
