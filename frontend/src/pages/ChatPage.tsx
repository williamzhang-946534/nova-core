import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Space, Tag, Typography } from "antd";
import { SendOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import StatusTag from "@/components/StatusTag";
import { sendChat } from "@/api/chat";
import { confirmTask } from "@/api/tasks";
import type { AgentChatResult } from "@/types/agent";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: AgentChatResult;
}

function createRequestId() {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `client-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

export default function ChatPage() {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [lastResult, setLastResult] = useState<AgentChatResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const chatMutation = useMutation({
    mutationFn: sendChat,
    onSuccess: (result) => {
      setLastResult(result);
      setMessages((previous) => [
        ...previous,
        { id: result.correlation_id, role: "assistant", content: result.reply, result },
      ]);
      if (result.task_id) {
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
    },
  });

  const confirmationMutation = useMutation({
    mutationFn: (confirmed: boolean) => {
      if (!lastResult?.task_id || !lastResult.confirmation_token) {
        throw new Error("当前没有可确认的任务。");
      }
      return confirmTask(lastResult.task_id, lastResult.confirmation_token, confirmed);
    },
    onSuccess: (task) => {
      const result = lastResult;
      setLastResult(null);
      setMessages((previous) => [
        ...previous,
        {
          id: `${task.id}-${task.status}`,
          role: "assistant",
          content:
            task.status === "completed"
              ? "任务已确认并完成，执行结果可在任务详情中查看。"
              : `任务当前状态：${task.status}。`,
          result: result ?? undefined,
        },
      ]);
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
    },
  });

  const canConfirm =
    lastResult?.status === "waiting_confirmation" &&
    Boolean(lastResult.task_id && lastResult.confirmation_token);
  const sortedMessages = useMemo(() => messages, [messages]);

  function submit() {
    const message = input.trim();
    if (!message || chatMutation.isPending) {
      return;
    }
    setActionError(null);
    setInput("");
    setMessages((previous) => [
      ...previous,
      { id: createRequestId(), role: "user", content: message },
    ]);
    chatMutation.mutate({ message, client_request_id: createRequestId() });
  }

  return (
    <section className="chat-layout">
      <header className="page-header">
        <div>
          <h1>AI 对话</h1>
          <p>自然语言查询与低风险控制。控制仍会经过候选计划校验、任务系统和工具执行链路。</p>
        </div>
      </header>

      {actionError ? <Alert type="error" showIcon message={actionError} /> : null}
      {chatMutation.isError ? <ApiErrorAlert error={chatMutation.error} /> : null}
      {confirmationMutation.isError ? <ApiErrorAlert error={confirmationMutation.error} /> : null}

      <Card className="chat-panel" title="会话">
        <div className="message-list" aria-live="polite">
          {sortedMessages.length === 0 ? (
            <Typography.Text type="secondary">
              输入例如“现在客厅灯是什么状态？”或“打开客厅灯”开始一次请求。
            </Typography.Text>
          ) : (
            sortedMessages.map((message) => (
              <article key={message.id} className={`message message-${message.role}`}>
                <div className="message-role">{message.role === "user" ? "我" : "Arvuno"}</div>
                <div>
                  <p>{message.content}</p>
                  {message.result ? (
                    <Space size={[4, 4]} wrap>
                      <StatusTag status={message.result.status} />
                      {message.result.intent ? <Tag>{message.result.intent}</Tag> : null}
                      {message.result.task_id ? <Tag>{message.result.task_id}</Tag> : null}
                    </Space>
                  ) : null}
                </div>
              </article>
            ))
          )}
          {chatMutation.isPending ? (
            <Typography.Text type="secondary">Arvuno 正在处理...</Typography.Text>
          ) : null}
        </div>

        {lastResult?.confirmation ? (
          <div className="confirmation-panel">
            <h3>需要确认</h3>
            <p>
              工具 {lastResult.confirmation.tool_name} · 风险 {lastResult.confirmation.risk_level}
            </p>
            <JsonBlock value={lastResult.confirmation.input} />
            <Space>
              <Button
                type="primary"
                loading={confirmationMutation.isPending}
                disabled={!canConfirm}
                onClick={() => confirmationMutation.mutate(true)}
              >
                确认执行
              </Button>
              <Button
                danger
                loading={confirmationMutation.isPending}
                disabled={!canConfirm}
                onClick={() => confirmationMutation.mutate(false)}
              >
                拒绝
              </Button>
            </Space>
          </div>
        ) : null}

        <div className="chat-input">
          <Input.TextArea
            value={input}
            autoSize={{ minRows: 2, maxRows: 4 }}
            placeholder="输入自然语言请求"
            onChange={(event) => setInput(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={chatMutation.isPending}
            disabled={input.trim().length === 0 || canConfirm}
            onClick={submit}
          >
            发送
          </Button>
        </div>
      </Card>
    </section>
  );
}
