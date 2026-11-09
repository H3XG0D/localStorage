import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Field, Input, cx } from "@/panel/ui/primitives";
import { diffSegments } from "@/panel/ui/diffText";

export { diffSegments, type DiffSegment } from "@/panel/ui/diffText";

export const SAVE_BAR_H = "4.5rem";

const LEAVE_MESSAGE = "Есть несохранённые изменения. Уйти без сохранения?";

function isInternalNavAnchor(anchor: HTMLAnchorElement): boolean {
  if (anchor.target && anchor.target !== "_self") return false;
  if (anchor.hasAttribute("download")) return false;
  if (anchor.closest("[data-allow-dirty-nav]")) return false;
  const href = anchor.getAttribute("href");
  if (!href || href.startsWith("mailto:") || href.startsWith("tel:")) return false;
  const url = new URL(anchor.href, window.location.href);
  if (url.origin !== window.location.origin) return false;
  if (url.pathname === window.location.pathname && url.search === window.location.search) return false;
  return true;
}

/**
 * Unsaved-changes guard. Panel uses BrowserRouter (not createBrowserRouter),
 * so react-router's useBlocker is not available — it throws outside a data router.
 * This hook covers: browser close/refresh, in-app <a>/<Link> clicks, Back, and
 * in-page tab switches via confirmLeave().
 */
export function useDirtyForm(dirty: boolean, options?: { message?: string }) {
  const message = options?.message ?? LEAVE_MESSAGE;

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (!dirty) return;
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement) || !isInternalNavAnchor(anchor)) return;
      if (!window.confirm(message)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [dirty, message]);

  useEffect(() => {
    if (!dirty) return;
    const onPopState = () => {
      if (!window.confirm(message)) window.history.go(1);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [dirty, message]);

  const confirmLeave = useCallback(() => {
    if (!dirty) return true;
    return window.confirm(message);
  }, [dirty, message]);

  return { confirmLeave };
}

export function SaveBar({
  dirty,
  invalid = false,
  dirtySectionCount = 0,
  onDiscard,
  onSave,
  saving = false,
  saveLabel = "Сохранить",
  discardLabel = "Отменить",
}: {
  dirty: boolean;
  invalid?: boolean;
  dirtySectionCount?: number;
  onDiscard: () => void;
  onSave: () => void;
  saving?: boolean;
  saveLabel?: string;
  discardLabel?: string;
}) {
  if (!dirty) return null;
  const status =
    dirtySectionCount > 0 ? `Изменено секций: ${dirtySectionCount}` : "Есть несохранённые изменения";
  return (
    <div
      data-save-bar=""
      className="sticky bottom-0 z-20 -mx-7 mt-4 flex min-h-[var(--save-bar-h)] flex-wrap items-center justify-between gap-3 border-t border-[var(--border-strong)] bg-[var(--bg-surface)]/95 px-7 py-3 backdrop-blur max-md:-mx-4 max-md:px-4"
    >
      <div className="min-w-0">
        <p className="text-[12.5px] text-[var(--text-secondary)]">{status}</p>
        {invalid ? <p className="text-[12px] text-[var(--red)]">Исправьте ошибки, чтобы сохранить</p> : null}
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" variant="ghost" onClick={onDiscard} disabled={saving}>
          {discardLabel}
        </Button>
        <Button type="button" variant="primary" onClick={onSave} disabled={invalid || saving}>
          {saving ? "Сохранение…" : saveLabel}
        </Button>
      </div>
    </div>
  );
}

export type FieldError = { id: string; message: string };

export function ValidationSummary({
  errors,
  focusToken = 0,
}: {
  errors: FieldError[];
  /** Bump after a failed save so the summary takes focus. */
  focusToken?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!errors.length || focusToken === 0) return;
    ref.current?.focus();
    ref.current?.scrollIntoView({ block: "start" });
  }, [errors.length, focusToken]);

  if (!errors.length) return null;

  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="alert"
      className="rounded-[var(--radius)] border border-[var(--red)]/40 bg-[var(--red-bg)] px-4 py-3 outline-none"
    >
      <p className="text-[13px] font-semibold text-[var(--red)]">
        Исправьте {errors.length === 1 ? "1 ошибку" : `ошибок: ${errors.length}`}
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {errors.map((error, index) => (
          <li key={`${error.id}-${index}`}>
            <a
              href={`#${error.id}`}
              className="text-[12.5px] text-[var(--text-primary)] underline-offset-2 hover:underline"
              onClick={(event) => {
                event.preventDefault();
                const field = document.getElementById(error.id);
                field?.focus();
                field?.scrollIntoView({ block: "center" });
              }}
            >
              {error.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SettingsSection({
  id,
  title,
  description,
  children,
  className,
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cx("flex flex-col gap-4", className)}>
      <div>
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {description ? <div className="mt-1 text-[12.5px] text-[var(--text-muted)]">{description}</div> : null}
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

export function DangerZone({
  title = "Опасная зона",
  description,
  confirmPhrase,
  actionLabel,
  onConfirm,
  disabled,
}: {
  title?: string;
  description: ReactNode;
  confirmPhrase: string;
  actionLabel: string;
  onConfirm: () => void;
  disabled?: boolean;
}) {
  const [typed, setTyped] = useState("");
  const matches = typed.trim() === confirmPhrase;
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--red)]/40 bg-[var(--red-bg)] p-5">
      <h2 className="text-[14px] font-semibold text-[var(--red)]">{title}</h2>
      <div className="mt-1 text-[12.5px] text-[var(--text-secondary)]">{description}</div>
      <div className="mt-4 flex max-w-md flex-col gap-3">
        <Field label={`Введите «${confirmPhrase}» для подтверждения`}>
          <Input
            value={typed}
            disabled={disabled}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setTyped(event.target.value)}
          />
        </Field>
        <Button
          type="button"
          variant="danger"
          disabled={disabled || !matches}
          onClick={() => {
            onConfirm();
            setTyped("");
          }}
        >
          {actionLabel}
        </Button>
      </div>
    </section>
  );
}

export function DiffRow({
  label,
  before,
  after,
}: {
  label?: string;
  before: string;
  after: string;
}) {
  const parts = diffSegments(String(before), String(after));
  const render = (segments: { text: string; changed: boolean }[]) =>
    segments.map((segment, index) =>
      segment.changed ? (
        <mark
          key={index}
          className="rounded-sm bg-[var(--yellow-bg)] text-[var(--text-primary)] ring-1 ring-[var(--yellow)]/35"
        >
          {segment.text}
        </mark>
      ) : (
        <span key={index}>{segment.text}</span>
      ),
    );
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 font-mono text-[12.5px]">
      {label ? <span className="font-sans text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</span> : null}
      <span className="text-[var(--text-muted)]">{parts.before.length ? render(parts.before) : "—"}</span>
      <span className="text-[var(--text-muted)]" aria-hidden>
        →
      </span>
      <span className="text-[var(--text-primary)]">{parts.after.length ? render(parts.after) : "—"}</span>
    </div>
  );
}
