import { useMemo, useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import { toast } from "sonner";
import {
  EXCHANGER_HMAC_CALLBACK_EXAMPLE,
  EXCHANGER_HMAC_CLIENT_STAT_BODY,
  EXCHANGER_HMAC_CLIENT_STAT_FIELDS,
  EXCHANGER_HMAC_CREATE_CRYPTO_BODY,
  EXCHANGER_HMAC_CREATE_FIELDS,
  EXCHANGER_HMAC_DEAL_FIELDS,
  EXCHANGER_HMAC_ENDPOINTS,
  EXCHANGER_HMAC_ERRORS,
  EXCHANGER_HMAC_HEADERS,
  EXCHANGER_HMAC_STATUSES,
  EXCHANGER_HMAC_STEPS,
  exchangerHmacBaseUrl,
  exchangerHmacCurlExample,
  exchangerHmacMarkdown,
  exchangerHmacPythonExample,
} from "@/lib/exchangerHmacDocs";
import { copyText } from "@/lib/exchangerDeal";
import { cn } from "@/lib/utils";

export type HmacGuideTone = "site" | "panel";

const TONE: Record<
  HmacGuideTone,
  {
    muted: string;
    pre: string;
    th: string;
    td: string;
    btn: string;
    title: string;
    ink: string;
  }
> = {
  site: {
    muted: "text-muted-foreground",
    pre: "overflow-x-auto rounded-lg border border-border bg-muted/30 p-3 pr-28 text-xs leading-5",
    th: "px-3 py-2 font-medium text-muted-foreground",
    td: "px-3 py-2",
    btn: "inline-flex h-9 items-center gap-1.5 rounded-md border border-input bg-background px-3 text-sm hover:bg-muted",
    title: "text-sm font-semibold",
    ink: "text-foreground",
  },
  panel: {
    muted: "text-secondary",
    pre: "overflow-x-auto rounded-[var(--radius-sm)] bg-elevated p-2 pr-24 text-[11px] leading-5",
    th: "px-2 py-1.5 font-medium text-muted",
    td: "px-2 py-1.5",
    btn: "inline-flex items-center gap-1 rounded-[var(--radius-sm)] border border-border px-2 py-1 text-[12px] hover:bg-overlay",
    title: "text-[12px] font-semibold uppercase tracking-wide text-muted",
    ink: "text-primary",
  },
};

function CopyCode({ value, tone }: { value: string; tone: HmacGuideTone }) {
  const [copied, setCopied] = useState(false);
  const t = TONE[tone];
  async function copy() {
    if (await copyText(value)) {
      setCopied(true);
      toast.success("Скопировано");
      window.setTimeout(() => setCopied(false), 2000);
      return;
    }
    toast.error("Не удалось скопировать");
  }
  return (
    <div className="relative">
      <pre className={t.pre}>{value}</pre>
      <button type="button" className={cn(t.btn, "absolute right-2 top-2")} onClick={() => void copy()}>
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? "Скопировано" : "Копировать"}
      </button>
    </div>
  );
}

function SimpleTable({
  tone,
  headers,
  rows,
}: {
  tone: HmacGuideTone;
  headers: string[];
  rows: string[][];
}) {
  const t = TONE[tone];
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            {headers.map((h) => (
              <th key={h} className={t.th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.join("|")} className="border-b border-border last:border-b-0">
              {row.map((cell, i) => (
                <td key={`${cell}-${i}`} className={cn(t.td, i < row.length - 1 ? "font-mono text-xs" : t.muted)}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExchangerHmacGuide({
  apiKey,
  origin,
  tone = "site",
}: {
  apiKey?: string | null;
  origin?: string;
  tone?: HmacGuideTone;
}) {
  const resolvedOrigin =
    origin || (typeof window !== "undefined" ? window.location.origin : "https://focuspay.org");
  const base = exchangerHmacBaseUrl(resolvedOrigin);
  const t = TONE[tone];
  const python = useMemo(
    () => exchangerHmacPythonExample(apiKey, resolvedOrigin).trim(),
    [apiKey, resolvedOrigin],
  );
  const curl = useMemo(() => exchangerHmacCurlExample(apiKey || "", resolvedOrigin), [apiKey, resolvedOrigin]);
  const markdown = useMemo(() => exchangerHmacMarkdown(resolvedOrigin, apiKey), [apiKey, resolvedOrigin]);

  async function copyGuide() {
    if (await copyText(markdown)) {
      toast.success("Инструкция скопирована");
      return;
    }
    toast.error("Не удалось скопировать");
  }

  function downloadGuide() {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "focuspay-shop-api.md";
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={t.btn} onClick={() => void copyGuide()}>
          <Copy className="size-3.5" /> Скопировать инструкцию
        </button>
        <button type="button" className={t.btn} onClick={downloadGuide}>
          <Download className="size-3.5" /> Скачать .md
        </button>
      </div>

      <section className="space-y-2">
        <h3 className={t.title}>Как это работает</h3>
        <ol className={cn("list-decimal space-y-1 pl-5 text-sm", t.muted)}>
          {EXCHANGER_HMAC_STEPS.map((step) => (
            <li key={step.n}>
              <span className={cn("font-medium", t.ink)}>{step.title}.</span> {step.text}
            </li>
          ))}
        </ol>
        <p className={cn("text-sm", t.muted)}>
          База: <span className={cn("font-mono", t.ink)}>{base}</span>. Отмена: POST /deals/{"{id}"}/cancel с телом {"{}"}, пока нет чека.
        </p>
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>С чего начать — Python</h3>
        <p className={cn("text-sm", t.muted)}>
          Каждый запрос подписывается: HMAC-SHA256 от timestamp и сырого тела. Секрет выдаёт администратор площадки, его показывают один раз.
        </p>
        <CopyCode value={python} tone={tone} />
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Curl</h3>
        <CopyCode value={curl} tone={tone} />
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Подпись</h3>
        <SimpleTable
          tone={tone}
          headers={["Header", "Значение"]}
          rows={EXCHANGER_HMAC_HEADERS.map((h) => [h.name, h.value])}
        />
        <ul className={cn("list-disc space-y-1 pl-5 text-sm", t.muted)}>
          <li>Строка подписи — вплотную timestamp и body, без пробела и перевода строки.</li>
          <li>GET: тела нет, подписываете только timestamp.</li>
          <li>Подписывайте ровно ту JSON-строку, которую отправляете. Пробелы и порядок ключей важны.</li>
          <li>Часы ±5 минут. Тот же timestamp с тем же телом второй раз не пройдёт.</li>
        </ul>
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Создать сделку</h3>
        <SimpleTable
          tone={tone}
          headers={["Поле", "Обяз.", "Описание"]}
          rows={EXCHANGER_HMAC_CREATE_FIELDS.map((f) => [f.name, f.req, f.desc])}
        />
        <p className={cn("text-sm", t.muted)}>Пример в крипте:</p>
        <CopyCode value={EXCHANGER_HMAC_CREATE_CRYPTO_BODY} tone={tone} />
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Что вернём</h3>
        <SimpleTable
          tone={tone}
          headers={["Поле", "Смысл"]}
          rows={EXCHANGER_HMAC_DEAL_FIELDS.map((f) => [f.name, f.desc])}
        />
        <SimpleTable
          tone={tone}
          headers={["status", "Смысл"]}
          rows={EXCHANGER_HMAC_STATUSES.map((s) => [s.status, s.desc])}
        />
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Эндпоинты</h3>
        <SimpleTable
          tone={tone}
          headers={["Метод", "Путь", "Зачем"]}
          rows={EXCHANGER_HMAC_ENDPOINTS.map((e) => [e.method, e.path, e.desc])}
        />
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Статистика клиента</h3>
        <p className={cn("text-sm", t.muted)}>
          Payfast в споре пишет /check uuid. Мы отвечаем той же карточкой, что по нашей заявке. Цифры — из вашей сводки. Без fingerprint все покупатели сливаются, без сводки клиент выглядит новым. ФИО и Telegram не слать.
        </p>
        <SimpleTable
          tone={tone}
          headers={["Поле", "Смысл"]}
          rows={EXCHANGER_HMAC_CLIENT_STAT_FIELDS.map((f) => [f.name, f.desc])}
        />
        <CopyCode value={EXCHANGER_HMAC_CLIENT_STAT_BODY} tone={tone} />
        <p className={cn("text-sm", t.muted)}>
          Лучше сразу в POST /deals полем client_stat, иначе POST /deals/{"{id}"}/client-stat. Проверка: GET /deals/{"{id}"}/check. Если оператор запросил видео — needs_operator_video в GET сделки.
        </p>
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Callback</h3>
        <p className={cn("text-sm", t.muted)}>
          Пришлём POST JSON на ваш callback_url. Подписи на callback нет — сверяйте deal_id и client_transaction_id у себя. event: credited, cancelled или extended. Ответьте 200.
        </p>
        <CopyCode value={EXCHANGER_HMAC_CALLBACK_EXAMPLE} tone={tone} />
      </section>

      <section className="space-y-2">
        <h3 className={t.title}>Ошибки</h3>
        <SimpleTable
          tone={tone}
          headers={["HTTP", "detail", "Почему"]}
          rows={EXCHANGER_HMAC_ERRORS.map((e) => [e.code, e.detail, e.why])}
        />
      </section>
    </div>
  );
}
