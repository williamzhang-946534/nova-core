import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import SystemStatusPage from "./pages/SystemStatusPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<SystemStatusPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
