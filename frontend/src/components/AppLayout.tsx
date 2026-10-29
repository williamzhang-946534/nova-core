import { Layout, Menu } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  ApiOutlined,
  BellOutlined,
  DashboardOutlined,
  CommentOutlined,
  UnorderedListOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

const { Content, Footer, Header, Sider } = Layout;

export default function AppLayout() {
  const location = useLocation();
  const selectedKey = `/${location.pathname.split("/")[1] ?? ""}`;

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" breakpoint="lg" collapsedWidth="0" theme="light">
        <div className="app-brand">Arvuno Core</div>
        <Menu
          mode="inline"
          items={[
            {
              key: "/",
              icon: <DashboardOutlined />,
              label: <Link to="/">系统概览</Link>,
            },
            {
              key: "/devices",
              icon: <ApiOutlined />,
              label: <Link to="/devices">设备</Link>,
            },
            {
              key: "/environment",
              icon: <DashboardOutlined />,
              label: <Link to="/environment">环境</Link>,
            },
            {
              key: "/events",
              icon: <UnorderedListOutlined />,
              label: <Link to="/events">事件</Link>,
            },
            {
              key: "/chat",
              icon: <CommentOutlined />,
              label: <Link to="/chat">AI 对话</Link>,
            },
            {
              key: "/tasks",
              icon: <UnorderedListOutlined />,
              label: <Link to="/tasks">任务</Link>,
            },
            {
              key: "/automations",
              icon: <ThunderboltOutlined />,
              label: <Link to="/automations">自动化</Link>,
            },
            {
              key: "/notifications",
              icon: <BellOutlined />,
              label: <Link to="/notifications">通知</Link>,
            },
            {
              key: "/settings",
              icon: <SettingOutlined />,
              label: <Link to="/settings">设置</Link>,
            },
          ]}
          selectedKeys={[selectedKey]}
        />
      </Sider>
      <Layout>
        <Header className="app-header">控制台</Header>
        <Content className="app-content">
          <Outlet />
        </Content>
        <Footer className="app-footer">Arvuno Core Web Console</Footer>
      </Layout>
    </Layout>
  );
}
