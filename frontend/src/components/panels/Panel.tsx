import { useId, type ReactNode } from "react";
import { Icon, type IconName } from "../ui/Icon";

/**
 * The shared analytical panel: a titled card whose body scrolls internally, so a long table or
 * list never stretches the dashboard. Layout height comes from the composition's grid area.
 */
export function Panel({
  title,
  subtitle,
  actions,
  footer,
  className,
  bodyClassName,
  children,
  label,
  icon,
}: {
  icon?: IconName;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
  /** Accessible name when it should differ from the visible title. */
  label?: string;
}) {
  const headingId = useId();
  return (
    <section
      className={`panel ${className ?? ""}`}
      aria-labelledby={label ? undefined : headingId}
      aria-label={label}
    >
      <header className="panel-head">
        {icon ? <Icon name={icon} size={22} className="panel-icon" /> : null}
        <div className="panel-titles">
          <h2 id={headingId}>{title}</h2>
          {subtitle ? <p className="panel-subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      <div className={`panel-body ${bodyClassName ?? ""}`}>{children}</div>
      {footer ? <footer className="panel-foot">{footer}</footer> : null}
    </section>
  );
}

/** Accessible tab switcher for panels that hold two views of the same snapshot data. */
export function PanelTabs<T extends string>({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: Array<{ key: T; label: string; disabled?: boolean }>;
  active: T;
  onChange: (key: T) => void;
  label: string;
}) {
  return (
    <div className="panel-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={tab.key === active}
          className={tab.key === active ? "panel-tab active" : "panel-tab"}
          disabled={tab.disabled}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
