export function LoadingState({ label = "Loading authorised analytics…" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      {label}
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
