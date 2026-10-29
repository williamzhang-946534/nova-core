import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import AutomationDetailPage from "./pages/AutomationDetailPage";
import AutomationListPage from "./pages/AutomationListPage";
import ChatPage from "./pages/ChatPage";
import DeviceDetailPage from "./pages/DeviceDetailPage";
import DeviceListPage from "./pages/DeviceListPage";
import EnvironmentPage from "./pages/EnvironmentPage";
import EventsPage from "./pages/EventsPage";
import NotificationsPage from "./pages/NotificationsPage";
import SystemOverviewPage from "./pages/SystemOverviewPage";
import SettingsPage from "./pages/SettingsPage";
import TaskDetailPage from "./pages/TaskDetailPage";
import TaskListPage from "./pages/TaskListPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<SystemOverviewPage />} />
        <Route path="devices" element={<DeviceListPage />} />
        <Route path="devices/:deviceId" element={<DeviceDetailPage />} />
        <Route path="environment" element={<EnvironmentPage />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="tasks" element={<TaskListPage />} />
        <Route path="tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="automations" element={<AutomationListPage />} />
        <Route path="automations/:automationId" element={<AutomationDetailPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
