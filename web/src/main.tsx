import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { followColorScheme } from "./styles/theme";

followColorScheme(document.documentElement, window.matchMedia("(prefers-color-scheme: dark)"));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
