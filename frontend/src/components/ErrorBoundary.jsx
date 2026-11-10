import { Component } from "react";

// Catches render errors in a page so the whole app doesn't go blank. Resets when the
// route changes (resetKey) so navigating elsewhere recovers.
export default class ErrorBoundary extends Component {
  state = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error) { return { error }; }

  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.key) return { error: null, key: props.resetKey };
    return null;
  }

  componentDidCatch(error, info) { console.error("Page crashed:", error, info); }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="bg-white border border-red-200 rounded-xl p-6 max-w-2xl" data-testid="page-error">
        <h3 className="font-head text-lg font-bold text-red-700">This page could not be displayed</h3>
        <p className="text-sm text-slate-600 mt-2">Something went wrong while loading it. Details:</p>
        <pre className="mt-3 text-xs bg-slate-50 border border-slate-200 rounded p-3 overflow-auto text-red-700">
          {String(this.state.error?.message || this.state.error)}
        </pre>
      </div>
    );
  }
}
