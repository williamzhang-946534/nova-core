import { Layout, Menu } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";

const { Content, Footer, Header, Sider } = Layout;

export default function AppLayout() {
  const location = useLocation();

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" breakpoint="lg" collapsedWidth="0" theme="light">
        <div className="app-brand">Nova Core</div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={[
            {
              key: "/",
              label: <Link to="/">系统状态</Link>,
            },
          ]}
        />
      </Sider>
      <Layout>
        <Header className="app-header">控制台</Header>
        <Content className="app-content">
          <Outlet />
        </Content>
        <Footer className="app-footer">Phase 1 · 工程初始化</Footer>
      </Layout>
    </Layout>
  );
}
