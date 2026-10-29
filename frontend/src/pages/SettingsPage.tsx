import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Form, Input, InputNumber, Tag } from "antd";
import { SaveOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import { getSettings, updateSettings } from "@/api/settings";
import { getApiBaseUrl, hasStoredApiToken, setApiBaseUrl, setApiToken } from "@/utils/api-config";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [tokenConfigured, setTokenConfigured] = useState(hasStoredApiToken());
  const [baseUrl, setBaseUrlValue] = useState(getApiBaseUrl());
  const [token, setToken] = useState("");
  const [form] = Form.useForm<{ event_poll_interval_seconds: number }>();

  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const updateMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  function saveConnection() {
    setApiBaseUrl(baseUrl);
    setApiToken(token);
    setToken("");
    setTokenConfigured(hasStoredApiToken());
    void queryClient.invalidateQueries();
  }

  return (
    <section className="page-stack narrow-page">
      <header className="page-header">
        <div>
          <h1>系统设置</h1>
          <p>管理 Web Console 连接和 Arvuno 非敏感运行偏好。</p>
        </div>
      </header>

      <Card title="Web Console 连接">
        <div className="connection-form">
          <label>
            Arvuno API Base URL
            <Input value={baseUrl} onChange={(event) => setBaseUrlValue(event.target.value)} />
          </label>
          <label>
            Arvuno API Token
            <Input.Password
              autoComplete="new-password"
              placeholder={tokenConfigured ? "已配置，输入新值可替换" : "输入 ARVUNO_API_TOKEN"}
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
        </div>
        <div className="form-actions">
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={saveConnection}
            disabled={
              baseUrl.trim().length === 0 || (!tokenConfigured && token.trim().length === 0)
            }
          >
            保存并重新连接
          </Button>
        </div>
        <Alert
          className="status-note"
          type={tokenConfigured ? "success" : "warning"}
          showIcon
          message={tokenConfigured ? "已配置本地访问令牌" : "尚未配置访问令牌"}
          description="令牌仅保存在当前浏览器，用于请求 Arvuno API；后端敏感配置仍必须通过受保护的环境变量管理。"
        />
      </Card>

      {settingsQuery.isPending ? (
        <PageLoading text="正在读取设置..." />
      ) : settingsQuery.isError ? (
        <ApiErrorAlert
          error={settingsQuery.error}
          onRetry={() => void settingsQuery.refetch()}
          retrying={settingsQuery.isFetching}
        />
      ) : (
        <>
          <Card title="运行配置">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="应用">
                {settingsQuery.data.runtime.app_name}
              </Descriptions.Item>
              <Descriptions.Item label="环境">
                {settingsQuery.data.runtime.environment}
              </Descriptions.Item>
              <Descriptions.Item label="AI Provider">
                <Tag>{settingsQuery.data.runtime.ai_provider}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Home Assistant">
                {settingsQuery.data.runtime.home_assistant_configured ? (
                  <Tag
                    color={
                      settingsQuery.data.runtime.home_assistant_write_enabled ? "orange" : "green"
                    }
                  >
                    {settingsQuery.data.runtime.home_assistant_write_enabled
                      ? "已配置，写操作开启"
                      : "已配置，写操作关闭"}
                  </Tag>
                ) : (
                  <Tag>未配置</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="允许实体数量">
                {settingsQuery.data.runtime.home_assistant_entity_limit}
              </Descriptions.Item>
              <Descriptions.Item label="设备轮询间隔">
                {settingsQuery.data.runtime.device_poll_interval_seconds} 秒
              </Descriptions.Item>
              <Descriptions.Item label="事件保留">
                {settingsQuery.data.runtime.event_retention_days} 天
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="控制台偏好">
            <Form
              form={form}
              layout="vertical"
              initialValues={settingsQuery.data.web_console}
              onFinish={(values) => updateMutation.mutate({ web_console: values })}
            >
              <Form.Item
                name="event_poll_interval_seconds"
                label="事件时间线轮询间隔（秒）"
                rules={[{ required: true, message: "请输入轮询间隔" }]}
              >
                <InputNumber min={2} max={300} precision={0} className="number-input" />
              </Form.Item>
              <div className="form-actions">
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<SaveOutlined />}
                  loading={updateMutation.isPending}
                >
                  保存偏好
                </Button>
              </div>
            </Form>
          </Card>
        </>
      )}
      {updateMutation.isError ? <ApiErrorAlert error={updateMutation.error} /> : null}
    </section>
  );
}
