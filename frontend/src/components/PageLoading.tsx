import { Spin } from "antd";

export default function PageLoading({ text = "正在加载数据..." }: { text?: string }) {
  return (
    <div className="loading-surface" aria-live="polite">
      <Spin tip={text}>
        <div className="loading-inner" />
      </Spin>
    </div>
  );
}
