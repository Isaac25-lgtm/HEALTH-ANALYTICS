"use client";

import { useEffect, useState } from "react";

/**
 * Loading indicator. A view that has not been opened since the last data refresh is calculated on
 * request; after a few seconds the wait is explained rather than left silent.
 */
export function LoadingState({ label = "Loading authorised analytics…" }: { label?: string }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div className="state-panel state-loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>
        {label}
        {slow ? (
          <span className="state-hint">
            This view is being calculated from the latest data for the first time. It opens straight away next time.
          </span>
        ) : null}
      </span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state-panel state-error" role="alert">
      {message}
    </div>
  );
}

export function PermissionDenied({ message }: { message: string }) {
  return (
    <div className="state-panel state-denied" role="alert">
      <h2>Access denied</h2>
      <p>{message}</p>
      <p>URL parameters cannot expand your authorised geography or programme scope.</p>
    </div>
  );
}

export function NoDataState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="state-inline" role="status">
      <h3 className="state-title">{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
