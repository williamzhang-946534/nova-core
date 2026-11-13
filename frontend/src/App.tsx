import { lazy, Suspense } from "react";
import type { ComponentType, ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./components/AppLayout";

const ActivePerceptionPage = lazy(() => import("./pages/ActivePerceptionPage"));
const AutomationDetailPage = lazy(() => import("./pages/AutomationDetailPage"));
const AutomationListPage = lazy(() => import("./pages/AutomationListPage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const DeviceDetailPage = lazy(() => import("./pages/DeviceDetailPage"));
const DeviceListPage = lazy(() => import("./pages/DeviceListPage"));
const EnvironmentPage = lazy(() => import("./pages/EnvironmentPage"));
const EventsPage = lazy(() => import("./pages/EventsPage"));
const HistoryPage = lazy(() => import("./pages/HistoryPage"));
const MemoryPage = lazy(() => import("./pages/MemoryPage"));
const MultimodalPage = lazy(() => import("./pages/MultimodalPage"));
const NotificationsPage = lazy(() => import("./pages/NotificationsPage"));
const PlanningPage = lazy(() => import("./pages/PlanningPage"));
const ProactivePage = lazy(() => import("./pages/ProactivePage"));
const ReasoningPage = lazy(() => import("./pages/ReasoningPage"));
const RetentionPage = lazy(() => import("./pages/RetentionPage"));
const RobotManagementPage = lazy(() => import("./pages/RobotManagementPage"));
const SpacesPage = lazy(() => import("./pages/SpacesPage"));
const StateEstimatesPage = lazy(() => import("./pages/StateEstimatesPage"));
const SystemOverviewPage = lazy(() => import("./pages/SystemOverviewPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const TaskDetailPage = lazy(() => import("./pages/TaskDetailPage"));
const TaskListPage = lazy(() => import("./pages/TaskListPage"));

type LazyRoute = {
  path: string;
  Component: ComponentType;
};

const lazyRoutes: LazyRoute[] = [
  { path: "", Component: SystemOverviewPage },
  { path: "devices", Component: DeviceListPage },
  { path: "devices/:deviceId", Component: DeviceDetailPage },
  { path: "robots", Component: RobotManagementPage },
  { path: "spaces", Component: SpacesPage },
  { path: "environment", Component: EnvironmentPage },
  { path: "events", Component: EventsPage },
  { path: "history", Component: HistoryPage },
  { path: "state-estimates", Component: StateEstimatesPage },
  { path: "memory", Component: MemoryPage },
  { path: "reasoning", Component: ReasoningPage },
  { path: "planning", Component: PlanningPage },
  { path: "proactive", Component: ProactivePage },
  { path: "active-perception", Component: ActivePerceptionPage },
  { path: "retention", Component: RetentionPage },
  { path: "multimodal", Component: MultimodalPage },
  { path: "chat", Component: ChatPage },
  { path: "tasks", Component: TaskListPage },
  { path: "tasks/:taskId", Component: TaskDetailPage },
  { path: "automations", Component: AutomationListPage },
  { path: "automations/:automationId", Component: AutomationDetailPage },
  { path: "notifications", Component: NotificationsPage },
  { path: "settings", Component: SettingsPage },
];

function PageBoundary({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div className="route-loading">正在加载页面...</div>}>{children}</Suspense>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {lazyRoutes.map(({ path, Component }) => (
          <Route
            key={path || "index"}
            path={path}
            element={
              <PageBoundary>
                <Component />
              </PageBoundary>
            }
          />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
