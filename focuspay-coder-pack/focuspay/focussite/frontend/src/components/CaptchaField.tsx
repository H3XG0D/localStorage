// Math-captcha field. The backend returns a signed token plus either an image
// (base64 PNG) or, on some deployments, a text question. We report the token and
// the user's typed answer to the parent and expose a refresh control.
import { useCallback, useEffect, useImperativeHandle, useState, forwardRef } from "react";
import { RefreshCw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { getCaptcha } from "@/lib/auth";

export interface CaptchaHandle {
  refresh: () => void;
}

export const CaptchaField = forwardRef<
  CaptchaHandle,
  { token: string; answer: string; onToken: (t: string) => void; onAnswer: (a: string) => void }
>(function CaptchaField({ answer, onToken, onAnswer }, ref) {
  const [image, setImage] = useState<string>("");
  const [question, setQuestion] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getCaptcha()
      .then((c) => {
        setImage(c.image || "");
        setQuestion(c.question || "");
        onToken(c.token);
      })
      .catch((e) => {
        setImage("");
        setQuestion("");
        const detail = e instanceof ApiError ? e.message : e instanceof Error ? e.message : "";
        setError(
          detail
            ? `Картинка не загрузилась (${detail}). Обновите или разрешите этот сайт в блокировщике.`
            : "Картинка не загрузилась. Обновите или разрешите этот сайт в блокировщике.",
        );
      })
      .finally(() => setLoading(false));
  }, [onToken]);

  useEffect(() => {
    load();
  }, [load]);

  useImperativeHandle(ref, () => ({ refresh: () => { onAnswer(""); load(); } }), [load, onAnswer]);

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="captcha">Проверка{question ? `: сколько будет ${question}?` : ""}</Label>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {image && (
        <div className="flex flex-wrap items-center gap-3">
          <img
            src={`data:image/png;base64,${image}`}
            alt="Captcha"
            className="block h-auto w-[260px] max-w-full rounded-lg border border-border bg-white"
          />
          <button
            type="button"
            aria-label="Обновить проверку"
            onClick={() => { onAnswer(""); load(); }}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg border border-input text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-95"
          >
            <RefreshCw className={loading ? "size-4 animate-spin" : "size-4"} />
          </button>
        </div>
      )}
      <div className="flex gap-2">
        <Input
          id="captcha"
          inputMode="text"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          autoComplete="off"
          value={answer}
          onChange={(e) => onAnswer(e.target.value.replace(/[^0-9A-Za-z]/g, "").toUpperCase())}
          placeholder="Цифры или буквы с картинки"
          className="font-mono"
          required
        />
        {!image && (
          <button
            type="button"
            aria-label="Обновить проверку"
            onClick={() => { onAnswer(""); load(); }}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg border border-input text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-95"
          >
            <RefreshCw className={loading ? "size-4 animate-spin" : "size-4"} />
          </button>
        )}
      </div>
    </div>
  );
});
