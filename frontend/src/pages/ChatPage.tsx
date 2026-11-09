import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Collapse, Input, Space, Switch, Tag, Typography } from "antd";
import { AudioMutedOutlined, AudioOutlined, SendOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import StatusTag from "@/components/StatusTag";
import { sendChat } from "@/api/chat";
import { getEnvironment } from "@/api/environment";
import { getVoiceState } from "@/api/voice";
import type { VoiceInteractionResult } from "@/api/voice";
import { confirmTask } from "@/api/tasks";
import type { AgentChatResult } from "@/types/agent";
import { useVoiceInteraction, voiceStageLabels } from "@/hooks/useVoiceInteraction";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: AgentChatResult;
  voiceResult?: VoiceInteractionResult;
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
  const [lastVoiceResult, setLastVoiceResult] = useState<VoiceInteractionResult | null>(null);
  const [environmentId, setEnvironmentId] = useState("");
  const [spaceId, setSpaceId] = useState("");
  const [userId, setUserId] = useState("web-user");
  const [captureConsentId, setCaptureConsentId] = useState("");
  const [processingConsentId, setProcessingConsentId] = useState("");
  const [ttsConsentId, setTtsConsentId] = useState("");
  const [requireWakeWord, setRequireWakeWord] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const environmentQuery = useQuery({ queryKey: ["environment"], queryFn: getEnvironment });
  const voiceStateQuery = useQuery({ queryKey: ["voice", "state"], queryFn: getVoiceState });

  useEffect(() => {
    const foundEnvironmentId = environmentQuery.data?.environment.environment_id;
    if (!environmentId && foundEnvironmentId) {
      setEnvironmentId(foundEnvironmentId);
    }
  }, [environmentId, environmentQuery.data]);

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

  const voiceEvents = useMemo(
    () => ({
      onUserMessage: (content: string) => {
        setMessages((previous) => [...previous, { id: createRequestId(), role: "user", content }]);
      },
      onAssistantMessage: (content: string, result?: VoiceInteractionResult) => {
        setMessages((previous) => [
          ...previous,
          {
            id: createRequestId(),
            role: "assistant",
            content,
            voiceResult: result,
          },
        ]);
      },
      onWaitingConfirmation: (result: VoiceInteractionResult) => {
        setLastVoiceResult(result);
      },
    }),
    [],
  );

  const voice = useVoiceInteraction(
    {
      environment_id: environmentId,
      space_id: spaceId || undefined,
      user_id: userId,
      capture_consent_id: captureConsentId,
      processing_consent_id: processingConsentId,
      tts_consent_id: ttsConsentId || undefined,
      require_wake_word: requireWakeWord,
    },
    voiceEvents,
  );

  const voiceConfirmationMutation = useMutation({
    mutationFn: (confirmed: boolean) => voice.confirm(confirmed),
    onSuccess: () => {
      setLastVoiceResult(null);
      setLastResult(null);
    },
  });

  const textCanConfirm =
    lastResult?.status === "waiting_confirmation" &&
    Boolean(lastResult.task_id && lastResult.confirmation_token);
  const voiceCanConfirm =
    lastVoiceResult?.interaction_state === "waiting_confirmation" &&
    Boolean(lastVoiceResult.task_id && lastVoiceResult.agent_result?.confirmation_token) &&
    voice.stage === "idle";
  const canConfirm = textCanConfirm || voiceCanConfirm;
  const microphoneEnabled = voiceStateQuery.data?.microphone_capture_enabled ?? false;
  const voiceConfirmation = voiceCanConfirm
    ? (lastVoiceResult?.agent_result?.confirmation ?? null)
    : null;
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
      {voice.error ? (
        <Alert type="error" showIcon closable message={voice.error} onClose={voice.clearError} />
      ) : null}

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
                  {message.voiceResult ? (
                    <Space size={[4, 4]} wrap>
                      <StatusTag status={message.voiceResult.interaction_state} />
                      {message.voiceResult.task_id ? (
                        <Tag>{message.voiceResult.task_id}</Tag>
                      ) : null}
                      {message.voiceResult.recognition ? (
                        <Tag>
                          {message.voiceResult.recognition.model_id}@
                          {message.voiceResult.recognition.model_version}
                        </Tag>
                      ) : null}
                    </Space>
                  ) : null}
                </div>
              </article>
            ))
          )}
          {chatMutation.isPending ? (
            <Typography.Text type="secondary">Arvuno 正在处理...</Typography.Text>
          ) : null}
          {voice.stage !== "idle" ? (
            <Tag color={voice.stage === "listening" ? "red" : "processing"}>
              {voiceStageLabels[voice.stage]}
            </Tag>
          ) : null}
        </div>

        <Collapse
          items={[
            {
              key: "voice",
              label: (
                <Space size={8}>
                  <AudioOutlined />
                  <span>语音交互</span>
                  <Tag color={microphoneEnabled ? "green" : "default"}>
                    {microphoneEnabled ? "可用" : "不可用"}
                  </Tag>
                  <Tag>{voiceStateQuery.data?.capture_mode ?? "加载中"}</Tag>
                </Space>
              ),
              children: (
                <div className="voice-settings">
                  <Input
                    placeholder="环境 ID"
                    value={environmentId}
                    onChange={(event) => setEnvironmentId(event.target.value)}
                  />
                  <Input
                    placeholder="空间 ID（可选）"
                    value={spaceId}
                    onChange={(event) => setSpaceId(event.target.value)}
                  />
                  <Input
                    placeholder="用户 ID"
                    value={userId}
                    onChange={(event) => setUserId(event.target.value)}
                  />
                  <Input
                    placeholder="采集授权 ID"
                    value={captureConsentId}
                    onChange={(event) => setCaptureConsentId(event.target.value)}
                  />
                  <Input
                    placeholder="处理授权 ID"
                    value={processingConsentId}
                    onChange={(event) => setProcessingConsentId(event.target.value)}
                  />
                  <Input
                    placeholder="播报授权 ID（可选）"
                    value={ttsConsentId}
                    onChange={(event) => setTtsConsentId(event.target.value)}
                  />
                  <Space size={12}>
                    <Switch
                      checked={requireWakeWord}
                      onChange={setRequireWakeWord}
                      aria-label="要求唤醒词"
                    />
                    <span>要求唤醒词</span>
                    <span>
                      持续采集：{voiceStateQuery.data?.continuous_capture_enabled ? "开启" : "关闭"}
                    </span>
                  </Space>
                </div>
              ),
            },
          ]}
        />

        {lastResult?.confirmation || voiceConfirmation ? (
          <div className="confirmation-panel">
            <h3>需要确认</h3>
            <p>
              工具 {(lastResult?.confirmation ?? voiceConfirmation)?.tool_name ?? "未知"} · 风险{" "}
              {(lastResult?.confirmation ?? voiceConfirmation)?.risk_level ?? "未知"}
            </p>
            <JsonBlock value={(lastResult?.confirmation ?? voiceConfirmation)?.input ?? {}} />
            <Space>
              <Button
                type="primary"
                loading={confirmationMutation.isPending || voiceConfirmationMutation.isPending}
                disabled={!canConfirm}
                onClick={() => {
                  if (voiceCanConfirm) {
                    void voiceConfirmationMutation.mutateAsync(true);
                  } else {
                    confirmationMutation.mutate(true);
                  }
                }}
              >
                确认执行
              </Button>
              <Button
                danger
                loading={confirmationMutation.isPending || voiceConfirmationMutation.isPending}
                disabled={!canConfirm}
                onClick={() => {
                  if (voiceCanConfirm) {
                    void voiceConfirmationMutation.mutateAsync(false);
                  } else {
                    confirmationMutation.mutate(false);
                  }
                }}
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
          <Button
            icon={voice.recording ? <AudioMutedOutlined /> : <AudioOutlined />}
            danger={voice.recording}
            disabled={voice.stage !== "idle" && voice.stage !== "listening"}
            onClick={() => {
              if (voice.recording) {
                voice.stopListening();
              } else {
                voice.startListening();
              }
            }}
          >
            {voice.recording ? "停止语音" : "语音输入"}
          </Button>
        </div>
      </Card>
    </section>
  );
}
