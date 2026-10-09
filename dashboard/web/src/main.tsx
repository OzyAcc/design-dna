import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import { ToastProvider } from "./lib";
import "./styles.css";

// a data router, so a page can hold navigation while its changes are saved (useBlocker); App keeps its own <Routes>
const router = createBrowserRouter([{ path: "*", element: <ToastProvider><App /></ToastProvider> }]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
