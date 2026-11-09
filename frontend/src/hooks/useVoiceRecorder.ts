import { useCallback, useEffect, useRef, useState } from "react";

const MAX_RECORDING_MS = 30_000;

function encodeWav(chunks: Float32Array[], sampleRate: number): Blob {
  const samples = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const writeText = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, samples * 2, true);

  let offset = 44;
  for (const chunk of chunks) {
    for (let index = 0; index < chunk.length; index += 1) {
      const value = Math.max(-1, Math.min(1, chunk[index]));
      view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
      offset += 2;
    }
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export interface VoiceRecorder {
  recording: boolean;
  start: () => Promise<void>;
  stop: () => void;
}

interface VoiceRecorderOptions {
  onRecordingComplete: (audio: Blob, durationMs: number) => void;
  onError: (message: string) => void;
}

export function useVoiceRecorder({
  onRecordingComplete,
  onError,
}: VoiceRecorderOptions): VoiceRecorder {
  const [recording, setRecording] = useState(false);
  const active = useRef(false);
  const chunks = useRef<Float32Array[]>([]);
  const startedAt = useRef(0);
  const timer = useRef<number | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const processor = useRef<ScriptProcessorNode | null>(null);
  const source = useRef<MediaStreamAudioSourceNode | null>(null);
  const mute = useRef<GainNode | null>(null);

  const release = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    source.current?.disconnect();
    processor.current?.disconnect();
    mute.current?.disconnect();
    stream.current?.getTracks().forEach((track) => track.stop());
    void audioContext.current?.close();
    source.current = null;
    processor.current = null;
    mute.current = null;
    stream.current = null;
    audioContext.current = null;
  }, []);

  const stop = useCallback(() => {
    if (!active.current) return;
    active.current = false;
    setRecording(false);
    const audio = encodeWav(chunks.current, audioContext.current?.sampleRate ?? 48_000);
    const durationMs = Math.max(1, Math.round(performance.now() - startedAt.current));
    release();
    chunks.current = [];
    onRecordingComplete(audio, durationMs);
  }, [onRecordingComplete, release]);

  const start = useCallback(async () => {
    if (active.current) return;
    chunks.current = [];
    startedAt.current = performance.now();
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const context = new AudioContext();
      audioContext.current = context;
      const input = context.createMediaStreamSource(stream.current);
      source.current = input;
      const node = context.createScriptProcessor(4096, 1, 1);
      processor.current = node;
      const silentOutput = context.createGain();
      mute.current = silentOutput;
      silentOutput.gain.value = 0;
      node.onaudioprocess = (event) => {
        if (!active.current) return;
        chunks.current.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      input.connect(node);
      node.connect(silentOutput);
      silentOutput.connect(context.destination);
      active.current = true;
      setRecording(true);
      timer.current = window.setTimeout(stop, MAX_RECORDING_MS);
    } catch {
      release();
      chunks.current = [];
      onError("无法访问麦克风，请检查浏览器授权。");
    }
  }, [onError, release, stop]);

  useEffect(
    () => () => {
      active.current = false;
      release();
    },
    [release],
  );

  return { recording, start, stop };
}
