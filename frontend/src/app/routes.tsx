import { createBrowserRouter } from "react-router";
import { ManagerLayout } from "./components/layouts/ManagerLayout";
import { AgentLayout } from "./components/layouts/AgentLayout";
import { ManagerDashboard } from "./components/manager/ManagerDashboard";
import { SessionInspector } from "./components/manager/SessionInspector";
import { SessionDetail } from "./components/manager/SessionDetail";
import { ManagerAssistant } from "./components/manager/ManagerAssistant";
import { KnowledgeBase } from "./components/manager/KnowledgeBase";
import { ReviewQueue } from "./components/manager/ReviewQueue";
import { NotificationsPage } from "./components/notifications/NotificationsPage";
import { AgentDashboard } from "./components/agent/AgentDashboard";
import { AgentCalls } from "./components/agent/AgentCalls";
import { AgentCallDetail } from "./components/agent/AgentCallDetail";
import { LandingPage } from "./components/LandingPage";

import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthProvider } from "./contexts/AuthContext";
import { SettingsPage } from "./components/SettingsPage";
import { ManagerSettings } from "./components/manager/ManagerSettings";
import { UnderDevelopment } from "./components/ui/UnderDevelopment";
import RouteErrorBoundary from "./components/ui/RouteErrorBoundary";
import Login from "./pages/Login";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <LandingPage />,
    errorElement: <RouteErrorBoundary />,
  },
  {
    path: "/login",
    element: <Login />,
    errorElement: <RouteErrorBoundary />,
  },
  {
    element: <ProtectedRoute />,
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        path: "/manager",
        element: <ManagerLayout />,
        errorElement: <RouteErrorBoundary />,
        children: [
          { index: true, element: <ManagerDashboard /> },
          { path: "inspector", element: <SessionInspector /> },
          { path: "inspector/:id", element: <SessionDetail /> },
          { path: "reviews", element: <ReviewQueue /> },
          { path: "notifications", element: <NotificationsPage /> },
          { path: "assistant", element: <ManagerAssistant /> },
          { path: "knowledge", element: <KnowledgeBase /> },
          { path: "settings", element: <ManagerSettings /> },
          { path: "*", element: <UnderDevelopment /> },
        ],
      },
      {
        path: "/agent",
        element: <AgentLayout />,
        errorElement: <RouteErrorBoundary />,
        children: [
          { index: true, element: <AgentDashboard /> },
          { path: "calls", element: <AgentCalls /> },
          { path: "calls/:id", element: <AgentCallDetail /> },
          { path: "notifications", element: <NotificationsPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <UnderDevelopment /> },
        ],
      },
    ],
  },
  {
    path: "*",
    element: <UnderDevelopment />,
    errorElement: <RouteErrorBoundary />,
  },
]);
