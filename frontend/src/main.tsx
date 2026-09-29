import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { AdminConsole } from "./components/AdminConsole";
import { useLang } from "./lib/i18n";
import "./styles/global.css";

const isAdminRoute = () => window.location.hash.replace(/^#/, "").startsWith("admin");

function Root() {
  // Subscribing here re-renders the whole tree (without remounting) on a language switch.
  useLang();
  const [admin, setAdmin] = useState(isAdminRoute());
  useEffect(() => {
    const onHashChange = () => setAdmin(isAdminRoute());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return admin ? <AdminConsole /> : <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
