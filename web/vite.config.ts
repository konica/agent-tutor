import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { port: 10453, strictPort: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: { include: /\.module\.css$/, modules: { classNameStrategy: "non-scoped" } },
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
