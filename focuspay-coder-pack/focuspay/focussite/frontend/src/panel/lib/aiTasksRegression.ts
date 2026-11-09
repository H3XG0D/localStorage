/** Safe UI regression helpers for Admin · /x8/ai-tasks (read-only agent). */

export const AI_TASKS_PATH = "/x8/ai-tasks";
export const AI_TASKS_HINT = "Очередь AI-задач";

export const SAFE_UI_ACTIONS = [
  "open_path",
  "assert_page_header",
  "change_status_filter",
  "select_task_row",
  "view_task_detail",
  "copy_cursor_prompt",
  "collect_console",
  "collect_network",
  "capture_screenshot_meta",
] as const;

export const FORBIDDEN_UI_ACTIONS = [
  "approve",
  "reject",
  "done",
  "finance",
  "payroll",
  "payout",
  "deploy",
  "git_commit",
  "git_push",
  "subprocess",
  "cursor_auto_apply",
  "execute_cursor_prompt",
  "delete",
  "ban",
  "broadcast",
] as const;

export type SafeUiAction = (typeof SAFE_UI_ACTIONS)[number];
export type ForbiddenUiAction = (typeof FORBIDDEN_UI_ACTIONS)[number];

export function isSafeUiAction(action: string): boolean {
  return (SAFE_UI_ACTIONS as readonly string[]).includes(action);
}

export function isForbiddenUiAction(action: string): boolean {
  return (FORBIDDEN_UI_ACTIONS as readonly string[]).includes(action);
}

export function assertRegressionPath(path: string): boolean {
  const p = (path || "").replace(/\/$/, "") || "";
  return p === AI_TASKS_PATH;
}

export type ConsoleCapture = {
  errors: string[];
  network: string[];
  dispose: () => void;
};

/** Capture console.error and failed fetch responses while walking the screen. */
export function startConsoleNetworkCapture(): ConsoleCapture {
  const errors: string[] = [];
  const network: string[] = [];
  const origError = console.error;
  const origFetch = window.fetch.bind(window);

  console.error = (...args: unknown[]) => {
    try {
      const msg = args.map((a) => (typeof a === "string" ? a : String(a))).join(" ").slice(0, 400);
      if (msg && !/focuspay_admin_token|Bearer |password|api[_-]?key/i.test(msg)) {
        errors.push(msg);
      }
    } catch {
      /* ignore */
    }
    origError(...args);
  };

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const res = await origFetch(input, init);
    try {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!res.ok && /\/api\/admin\/ai-tasks/.test(url) && !/\/approve|\/reject|\/done/.test(url)) {
        network.push(`${res.status} ${url}`.slice(0, 300));
      }
    } catch {
      /* ignore */
    }
    return res;
  };

  return {
    errors,
    network,
    dispose: () => {
      console.error = origError;
      window.fetch = origFetch;
    },
  };
}

export function buildRegressionPayload(opts: {
  statusFilter: string;
  selectedTaskId?: number | null;
  consoleErrors?: string[];
  networkErrors?: string[];
  pageTitle?: string;
  version?: string;
}) {
  return {
    path: AI_TASKS_PATH,
    hint: AI_TASKS_HINT,
    page_title: opts.pageTitle || "AI · задачи от операторов",
    status_filter: opts.statusFilter || "review",
    selected_task_id: opts.selectedTaskId ?? undefined,
    console_errors: (opts.consoleErrors || []).slice(0, 40),
    network_errors: (opts.networkErrors || []).slice(0, 40),
    version: opts.version,
  };
}
