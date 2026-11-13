import { Layout, Menu } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  ApiOutlined,
  BellOutlined,
  BulbOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  CommentOutlined,
  HistoryOutlined,
  HomeOutlined,
  RobotOutlined,
  DatabaseOutlined,
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
              key: "/robots",
              icon: <RobotOutlined />,
              label: <Link to="/robots">机器人</Link>,
            },
            {
              key: "/spaces",
              icon: <HomeOutlined />,
              label: <Link to="/spaces">空间</Link>,
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
              key: "/history",
              icon: <HistoryOutlined />,
              label: <Link to="/history">历史</Link>,
            },
            {
              key: "/state-estimates",
              icon: <DeploymentUnitOutlined />,
              label: <Link to="/state-estimates">状态投影</Link>,
            },
            {
              key: "/memory",
              icon: <DatabaseOutlined />,
              label: <Link to="/memory">记忆</Link>,
            },
            {
              key: "intelligence",
              icon: <BulbOutlined />,
              label: "智能",
              children: [
                {
                  key: "/reasoning",
                  label: <Link to="/reasoning">推理</Link>,
                },
                {
                  key: "/planning",
                  label: <Link to="/planning">规划</Link>,
                },
                {
                  key: "/proactive",
                  label: <Link to="/proactive">主动建议</Link>,
                },
                {
                  key: "/active-perception",
                  label: <Link to="/active-perception">主动感知</Link>,
                },
              ],
            },
            {
              key: "governance",
              icon: <DatabaseOutlined />,
              label: "治理",
              children: [
                {
                  key: "/retention",
                  label: <Link to="/retention">数据保留</Link>,
                },
                {
                  key: "/multimodal",
                  label: <Link to="/multimodal">多模态</Link>,
                },
              ],
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
