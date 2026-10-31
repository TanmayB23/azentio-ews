import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/outfit";
import "./styles.css";
import { Layout } from "./components/Layout";
import { WorkspaceProvider } from "./state";
import { Overview } from "./pages/Overview";
import { Watchlist } from "./pages/Watchlist";
import { CustomerPage } from "./pages/Customer";
import { Portfolio } from "./pages/Portfolio";
import { DataPage } from "./pages/Data";
import { Audit } from "./pages/Audit";
import { SettingsPage } from "./pages/Settings";
import { Help } from "./pages/Help";
import { Empty } from "./components/ui";

const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <WorkspaceProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="watchlist" element={<Watchlist />} />
              <Route path="customers/:customerId" element={<CustomerPage />} />
              <Route path="portfolio" element={<Portfolio />} />
              <Route path="data" element={<DataPage />} />
              <Route path="audit" element={<Audit />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="help" element={<Help />} />
              <Route path="*" element={<Empty title="Page not found">Use the menu to find your way back.</Empty>} />
            </Route>
          </Routes>
        </WorkspaceProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
