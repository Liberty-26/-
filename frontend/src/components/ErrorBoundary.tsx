// SteelDigitize Pro — 错误边界（兜底显示，避免白屏；开发期用于定位）
import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  stack: string;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, stack: '' };

  static getDerivedStateFromError(error: Error): State {
    return { error, stack: '' };
  }

  componentDidCatch(_error: Error, info: { componentStack?: string }) {
    this.setState({ stack: info.componentStack || '' });
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, fontFamily: 'monospace', fontSize: 13, color: '#b91c1c', background: '#fff', height: '100vh', overflow: 'auto' }}>
          <h2 style={{ marginBottom: 12 }}>页面出错了（已捕获）</h2>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{String(this.state.error.message)}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', marginTop: 16, color: '#374151' }}>{this.state.stack}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}
