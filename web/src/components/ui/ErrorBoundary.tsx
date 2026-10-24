import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  /** What failed, in a few words, for the fallback's message. */
  label: string;
  children: ReactNode;
  /** A custom fallback; the default explains what happened and offers a retry. */
  fallback?: (error: Error, retry: () => void) => ReactNode;
}

/** Keeps one failing part of a screen from taking down the rest (the 3D view falls back to 2D, for example). */
export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`OffBall: ${this.props.label} failed`, error, info.componentStack);
  }

  retry = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.retry);
    return (
      <div className="card error-card" role="alert">
        <h2 className="card-h3">{this.props.label} stopped working</h2>
        <p className="muted" style={{ fontSize: 14, lineHeight: 1.5, marginBottom: 12 }}>
          The rest of OffBall still works. You can try again, or go back to all screens.
        </p>
        <div className="cluster">
          <button type="button" className="btn btn-primary press" onClick={this.retry}>
            Try again
          </button>
          <a href="#/" className="btn btn-ghost press">
            All screens
          </a>
        </div>
      </div>
    );
  }
}
