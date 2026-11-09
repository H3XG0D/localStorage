import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { getReviewOffer, submitReview, type ReviewOffer } from "@/lib/user";

export function ReviewBonusCard() {
  const [offer, setOffer] = useState<ReviewOffer | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getReviewOffer()
      .then((next) => {
        if (!cancelled) setOffer(next);
      })
      .catch(() => {
        if (!cancelled) setOffer(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!offer || (!offer.eligible && offer.reason !== "pending")) return null;

  const amount = Number(offer.text_rub || 0);
  const minLen = Number(offer.min_len || 20);
  const ready = text.trim().length >= minLen;

  async function onSubmit() {
    if (!ready) return;
    setBusy(true);
    try {
      const res = await submitReview(text.trim());
      setOffer({
        eligible: false,
        pending: true,
        reason: "pending",
        order_id: res.order_id ?? offer?.order_id ?? null,
        text_rub: res.text_rub ?? amount,
        min_len: minLen,
        needs_photo: false,
      });
      setText("");
      toast.success("Отзыв отправлен на проверку");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось отправить отзыв");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Отзыв · {amount} ₽</CardTitle>
        <CardDescription>
          Напишите текст здесь, в кабинете. Скрин не нужен: после проверки {amount} ₽ придут на баланс этого аккаунта.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {offer.reason === "pending" ? (
          <p className="text-sm leading-6 text-muted-foreground">
            Отзыв уже на проверке. После одобрения {amount} ₽ появятся на балансе.
          </p>
        ) : (
          <div className="space-y-3">
            <textarea
              value={text}
              maxLength={2000}
              rows={4}
              placeholder="Как прошёл обмен"
              onChange={(e) => setText(e.target.value)}
              className="flex w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">От {minLen} символов</p>
              <Button onClick={onSubmit} disabled={busy || !ready}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : "Отправить отзыв"}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
