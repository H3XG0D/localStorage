import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Gift, Loader2, Send } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { PublicHeader } from "@/components/PublicHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getDeviceFingerprint } from "@/lib/api";
import { getInviteInfo, getRefInfo, trackAttribution, type RefInfo } from "@/lib/public";

const DONE_KEY = "focuspay_attr_tracked";

export function RefLanding({ kind }: { kind: "ref" | "invite" }) {
  const { token = "" } = useParams();
  const [info, setInfo] = useState<RefInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!token) return;
    const fetchInfo = kind === "ref" ? getRefInfo : getInviteInfo;
    fetchInfo(token)
      .then((data) => {
        setInfo(data);
        // Track attribution once per token.
        if (window.localStorage.getItem(DONE_KEY) !== token) {
          const refKind = kind === "ref" ? "promo" : "user";
          trackAttribution(refKind, token, getDeviceFingerprint())
            .then(() => window.localStorage.setItem(DONE_KEY, token))
            .catch(() => undefined);
        }
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [token, kind]);

  return (
    <div className="min-h-screen bg-background">
      <PublicHeader />
      <main className="grid-paper flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-16">
        {loading ? (
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        ) : notFound || !info ? (
          <Card className="w-full max-w-md">
            <CardHeader>
              <CardTitle>Ссылка недействительна</CardTitle>
              <CardDescription>Приглашение не найдено или больше не активно.</CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild className="w-full">
                <Link to="/">На главную<ArrowRight data-icon="inline-end" /></Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="w-full max-w-md">
            <Card className="overflow-hidden shadow-xl shadow-foreground/5">
              <CardHeader className="border-b border-border bg-muted/40">
                <div className="flex size-11 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Gift />
                </div>
                <CardTitle className="mt-3 text-2xl">
                  {info.name || "Вас пригласили в FocusPay"}
                </CardTitle>
                <CardDescription>
                  {info.bonus_percent
                    ? `Бонус ${info.bonus_percent}% по приглашению активируется автоматически.`
                    : "Обменивайте криптовалюту с бонусами по приглашению."}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 pt-5">
                <Button size="lg" asChild>
                  <Link to="/exchange">Начать обмен<ArrowRight data-icon="inline-end" /></Link>
                </Button>
                {info.telegram_url && (
                  <Button size="lg" variant="outline" asChild>
                    <a href={info.telegram_url} target="_blank" rel="noreferrer">
                      <Send data-icon="inline-start" />
                      Открыть в Telegram
                    </a>
                  </Button>
                )}
                <p className="text-center text-xs text-muted-foreground">
                  Бонус закрепится за вами после регистрации или создания заявки.
                </p>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </main>
    </div>
  );
}
