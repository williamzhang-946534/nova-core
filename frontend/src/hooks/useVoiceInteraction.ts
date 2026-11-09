import { useCallback, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { confirmVoiceTask, getTtsAudio, processVoice } from "@/api/voice";
import type { VoiceInteractionResult } from "@/api/voice";
import { useVoiceRecorder } from "./useVoiceRecorder";

export const voiceStages = ["idle", "listening", "recognizing", "executing", "speaking"] as const;

export type VoiceStage = (typeof voiceStages)[number];

export const voiceStageLabels: Record<VoiceStage, string> = {
  idle: "待机，麦克风关闭",
  listening: "正在录音",
  recognizing: "识别处理中",
  executing: "正在执行确认",
  speaking: "正在播报",
};

export interface VoiceInteractionConfig {
  environment_id: string;
  user_id: string;
  capture_consent_id: string;
  processing_consent_id: string;
  space_id?: string;
  tts_consent_id?: string;
  require_wake_word?: boolean;
}

interface VoiceInteractionEvents {
  onUserMessage: (content: string) => void;
  onAssistantMessage: (content: string, result?: VoiceInteractionResult) => void;
  onWaitingConfirmation: (result: VoiceInteractionResult) => void;
}

interface VoiceInteraction {
  stage: VoiceStage;
  recording: boolean;
  error: string | null;
  startListening: () => void;
  stopListening: () => void;
  confirm: (confirmed: boolean) => Promise<void>;
  clearError: () => void;
}

export function useVoiceInteraction(
  config: VoiceInteractionConfig,
  events: VoiceInteractionEvents,
): VoiceInteraction {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<VoiceStage>("idle");
  const [error, setError] = useState<string | null>(null);
  const confirmationRef = useRef<VoiceInteractionResult | null>(null);

  const canProcess =
    config.environment_id.length > 0 &&
    config.user_id.length > 0 &&
    config.capture_consent_id.length > 0 &&
    config.processing_consent_id.length > 0;

  const play = useCallback(async (assetId: string | null) => {
    if (!assetId) return;
    setStage("speaking");
    try {
      const audio = new Audio(URL.createObjectURL(await getTtsAudio(assetId)));
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        void audio.play().catch(() => resolve());
      });
    } catch {
      setError("语音播报不可用，文字回答已保留。");
    } finally {
      setStage("idle");
    }
  }, []);

  const handleResult = useCallback(
    async (result: VoiceInteractionResult) => {
      if (result.transcript) {
        events.onUserMessage(result.transcript);
      }
      if (result.reply && result.interaction_state !== "waiting_confirmation") {
        events.onAssistantMessage(result.reply, result);
      } else if (result.reply) {
        events.onAssistantMessage(result.reply, result);
        events.onWaitingConfirmation(result);
        confirmationRef.current = result;
      }
      if (result.agent_result?.task_id) {
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
      await play(result.tts_asset_id);
      setStage("idle");
    },
    [events, play, queryClient],
  );

  const submitAudio = useCallback(
    async (audio: Blob, durationMs: number) => {
      if (!canProcess) {
        setError("语音输入需要环境、用户 ID、采集授权和处理授权。");
        setStage("idle");
        return;
      }
      setStage("recognizing");
      setError(null);
      try {
        const result = await processVoice({
          ...config,
          audio,
          duration_ms: durationMs,
          client_captured_at: new Date().toISOString(),
          client_time_source: "device_clock",
          client_time_uncertainty_ms: 250,
        });
        await handleResult(result);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "语音识别失败。");
        setStage("idle");
      }
    },
    [canProcess, config, handleResult],
  );

  const recorder = useVoiceRecorder({
    onRecordingComplete: (audio, durationMs) => {
      void submitAudio(audio, durationMs);
    },
    onError: setError,
  });

  const startListening = useCallback(() => {
    if (stage !== "idle" || !canProcess) return;
    setError(null);
    setStage("listening");
    void recorder.start().then(() => {
      setStage(recorder.recording ? "listening" : "idle");
    });
  }, [canProcess, recorder, stage]);

  const stopListening = useCallback(() => {
    if (stage !== "listening") return;
    setStage("recognizing");
    recorder.stop();
  }, [recorder, stage]);

  const confirm = useCallback(
    async (confirmed: boolean) => {
      const pending = confirmationRef.current;
      if (!pending?.task_id || !pending.agent_result?.confirmation_token || !canProcess) {
        setError("当前没有可确认的语音任务。");
        return;
      }
      setStage("executing");
      setError(null);
      try {
        const result = await confirmVoiceTask({
          ...config,
          task_id: pending.task_id,
          confirmation_token: pending.agent_result.confirmation_token,
          confirmed,
        });
        confirmationRef.current = null;
        events.onAssistantMessage(result.reply ?? "任务确认状态已更新。", result);
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
        await play(result.tts_asset_id);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "任务确认失败。");
        setStage("idle");
      }
    },
    [canProcess, config, events, play, queryClient],
  );

  return useMemo(
    () => ({
      stage,
      recording: recorder.recording,
      error,
      startListening,
      stopListening,
      confirm,
      clearError: () => setError(null),
    }),
    [confirm, error, recorder.recording, stage, startListening, stopListening],
  );
}
