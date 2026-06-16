"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/shared/ui/button";

type Props = {
  children: ReactNode;
};

type State = {
  error: Error | null;
};

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div className="app-error-fallback">
          <h1 className="app-error-fallback-title">Что-то пошло не так</h1>
          <p className="app-error-fallback-message">
            Произошла непредвиденная ошибка. Попробуйте обновить экран или перезагрузить страницу.
          </p>
          <div className="app-error-fallback-actions">
            <Button type="button" onClick={this.handleRetry}>
              Попробовать снова
            </Button>
            <Button type="button" variant="outline" onClick={() => window.location.reload()}>
              Перезагрузить
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
