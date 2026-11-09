import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check, ChevronDown, Copy, Menu, Quote, ShieldCheck, Sparkles, WalletCards, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { CasinoOpenLink } from "@/casino/casinoPaths";
import { Brand } from "@/components/Brand";
import { StatusDot } from "@/components/StatusDot";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Reveal } from "@/components/Reveal";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { RateTicker } from "@/components/RateTicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { quoteBuyFromRub } from "@/lib/buyQuote";
import { CRYPTO_META, getRates, getReviews, type CryptoId, type RatesResponse, type Review } from "@/lib/public";
import { useReferralAttribution } from "@/lib/useAttribution";
import { useSession } from "@/lib/session";
import { formatMoney } from "@/lib/utils";

const ASSETS: CryptoId[] = ["usdt", "btc", "ltc", "trx"];
const RATES_POLL_MS = 30_000;

function ExchangeWidget({ rates }: { rates: RatesResponse | null }) {
  const navigate = useNavigate();
  const [direction, setDirection] = useState<"buy" | "sell">("buy");
  const [asset, setAsset] = useState<CryptoId>("usdt");
  const [amount, setAmount] = useState("50000");
  const meta = CRYPTO_META[asset];
  const rate = rates?.rates?.[asset];
  const buyQuote = useMemo(() => {
    if (direction !== "buy") return null;
    return quoteBuyFromRub(Number(amount || 0), rate, rates?.public_tariffs?.buy_spread_auto_tiers);
  }, [amount, direction, rate, rates?.public_tariffs?.buy_spread_auto_tiers]);
  const price = direction === "buy"
    ? (rate && buyQuote ? Number(rate.market) * (1 + buyQuote.pct / 100) : rate?.buy)
    : rate?.sell;
  const result = useMemo(() => {
    if (direction === "buy") return buyQuote?.crypto ?? 0;
    const p = Number(price || 0);
    if (!p) return 0;
    return Number(amount || 0) * p;
  }, [amount, buyQuote, direction, price]);

  function submit() {
    const params = new URLSearchParams({ direction, asset, amount: String(amount || "") });
    navigate(`/exchange?${params.toString()}`);
  }

  return (
    <Card id="exchange" className="overflow-hidden border-foreground/15 shadow-xl shadow-foreground/5">
      <CardHeader className="border-b border-border bg-muted/40 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Быстрый обмен</CardTitle>
            <CardDescription className="mt-1">Расчёт по актуальному курсу</CardDescription>
          </div>
          <StatusDot label={rates ? "Курс обновлён" : "Загрузка…"} tone={rates ? "positive" : "neutral"} />
        </div>
        <Tabs value={direction} onValueChange={(v) => setDirection(v as "buy" | "sell")} className="mt-3">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="buy">Покупаю крипту</TabsTrigger>
            <TabsTrigger value="sell">Продаю крипту</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="amount">{direction === "buy" ? "Нужная сумма крипты, RUB" : `Отдаю, ${meta.label}`}</Label>
          <div className="relative">
            <Input
              id="amount"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="pr-16 font-mono text-lg"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-muted-foreground">
              {direction === "buy" ? "RUB" : meta.label}
            </span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="asset">{direction === "buy" ? "Получаю" : "Отдаю актив"}</Label>
          <Select value={asset} onValueChange={(v) => setAsset(v as CryptoId)}>
            <SelectTrigger id="asset">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ASSETS.map((id) => (
                <SelectItem key={id} value={id}>
                  {CRYPTO_META[id].label} <span className="ml-1 text-muted-foreground">· {CRYPTO_META[id].detail}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Ориентировочный курс</span>
            <span className="font-mono text-foreground">
              {price ? <>1 {meta.label} ≈ <AnimatedNumber value={price} /> ₽</> : "—"}
            </span>
          </div>
          {direction === "buy" && Number(amount || 0) > 0 && !buyQuote && (
            <p className="mt-2 text-xs text-destructive">Курс CoinGecko временно недоступен. Попробуйте позже.</p>
          )}
          <div className="mt-3 flex items-end justify-between gap-3">
            <span className="text-sm text-muted-foreground">Вы получите примерно</span>
            <span className="font-mono text-2xl font-semibold tracking-tight">
              <AnimatedNumber value={result} maximumFractionDigits={6} />{" "}
              <span className="text-sm font-medium text-muted-foreground">{direction === "buy" ? meta.label : "RUB"}</span>
            </span>
          </div>
          {direction === "buy" && buyQuote && (
            <div className="mt-2 flex items-end justify-between gap-3 text-sm">
              <span className="text-muted-foreground">К оплате</span>
              <span className="font-mono font-semibold">
                <AnimatedNumber value={buyQuote.pay} /> ₽
              </span>
            </div>
          )}
        </div>
        <Button size="lg" className="w-full" disabled={Number(amount) <= 0 || (direction === "buy" && !buyQuote)} onClick={submit}>
          Продолжить обмен
          <ArrowRight data-icon="inline-end" />
        </Button>
        <p className="text-center text-xs leading-relaxed text-muted-foreground">
          Итоговый курс и реквизиты вы увидите на следующем шаге.
        </p>
      </CardContent>
    </Card>
  );
}

function ReviewsSection() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [channelUrl, setChannelUrl] = useState("https://t.me/focuspayr");
  useEffect(() => {
    getReviews(12)
      .then((r) => {
        setReviews(r.reviews || []);
        if (r.channel_url) setChannelUrl(r.channel_url);
      })
      .catch(() => undefined);
  }, []);

  if (!reviews.length) return null;
  // Duplicate the list so the marquee loops seamlessly.
  const lane = [...reviews, ...reviews];
  return (
    <section id="reviews" className="overflow-hidden border-t border-border py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <Reveal>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[.18em] text-muted-foreground">Отзывы клиентов</p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">Люди уже обменивают спокойно.</h2>
            </div>
            <a
              href={channelUrl}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
            >
              Смотреть в Telegram →
            </a>
          </div>
        </Reveal>
      </div>
      <div className="group relative mt-8 [mask-image:linear-gradient(90deg,transparent,#000_6%,#000_94%,transparent)]">
        <div className="flex w-max gap-3 px-4 animate-[ticker_60s_linear_infinite] group-hover:[animation-play-state:paused] motion-reduce:animate-none motion-reduce:flex-wrap motion-reduce:justify-center">
          {lane.map((rev, i) => (
            <div
              key={`${rev.id}-${i}`}
              className="flex w-[300px] shrink-0 flex-col rounded-xl border border-border bg-card p-5 sm:w-[340px]"
            >
              <Quote className="text-muted-foreground/50" />
              <p className="mt-3 line-clamp-4 flex-1 whitespace-pre-line text-sm leading-6">{rev.text}</p>
              <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{rev.author_name || "Клиент"}</span>
                {rev.published_at && (
                  <span className="font-mono">
                    {new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" }).format(new Date(rev.published_at))}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function PublicHome() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [rates, setRates] = useState<RatesResponse | null>(null);
  const { isAuthed } = useSession();
  const timer = useRef<number | null>(null);
  useReferralAttribution();

  useEffect(() => {
    let alive = true;
    const load = () => getRates().then((r) => alive && setRates(r)).catch(() => undefined);
    load();
    timer.current = window.setInterval(load, RATES_POLL_MS);
    return () => {
      alive = false;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  const loginHref = isAuthed ? "/cabinet" : "/login";
  const loginLabel = isAuthed ? "Кабинет" : "Войти";

  return (
    <div className="min-h-screen overflow-x-hidden bg-background">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link to="/" aria-label="FocusPay">
            <Brand />
          </Link>
          <nav className="hidden items-center gap-7 text-sm text-muted-foreground md:flex">
            <a className="transition-colors hover:text-foreground" href="#exchange">Обмен</a>
            <CasinoOpenLink className="transition-colors hover:text-foreground">FocusBet</CasinoOpenLink>
            <a className="transition-colors hover:text-foreground" href="#process">Как это работает</a>
            <a className="transition-colors hover:text-foreground" href="#reviews">Отзывы</a>
            <a className="transition-colors hover:text-foreground" href="#security">Безопасность</a>
          </nav>
          <div className="hidden items-center gap-3 md:flex">
            <ThemeToggle />
            <Button variant="ghost" asChild>
              <Link to={loginHref}>{loginLabel}</Link>
            </Button>
            <Button asChild>
              <a href="#exchange">Начать обмен<ArrowRight data-icon="inline-end" /></a>
            </Button>
          </div>
          <div className="flex items-center gap-1 md:hidden">
            <ThemeToggle />
            <Button variant="ghost" size="icon" aria-label="Открыть меню" onClick={() => setMenuOpen(true)}>
              <Menu data-icon="inline-start" />
            </Button>
          </div>
        </div>
      </header>

      <AnimatePresence>
        {menuOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 bg-background p-5 md:hidden"
          >
            <div className="flex items-center justify-between">
              <Brand compact />
              <Button variant="ghost" size="icon" aria-label="Закрыть меню" onClick={() => setMenuOpen(false)}>
                <X data-icon="inline-start" />
              </Button>
            </div>
            <nav className="mt-16 flex flex-col gap-5 text-2xl font-semibold">
              <a href="#exchange" onClick={() => setMenuOpen(false)}>Обмен</a>
              <CasinoOpenLink onClick={() => setMenuOpen(false)}>FocusBet</CasinoOpenLink>
              <a href="#process" onClick={() => setMenuOpen(false)}>Как это работает</a>
              <a href="#reviews" onClick={() => setMenuOpen(false)}>Отзывы</a>
              <a href="#security" onClick={() => setMenuOpen(false)}>Безопасность</a>
              <Link to={loginHref} onClick={() => setMenuOpen(false)}>{loginLabel}</Link>
            </nav>
          </motion.div>
        )}
      </AnimatePresence>

      <main>
        <section className="grid-paper relative border-b border-border">
          <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1.05fr_.95fr] lg:px-8 lg:py-28">
            <motion.div className="min-w-0" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
              <div className="mb-6 flex items-center gap-3">
                <StatusDot label="Работаем 24/7" tone="positive" />
                <span className="text-xs text-muted-foreground">проверенный обмен</span>
              </div>
              <h1 className="max-w-3xl text-5xl font-extrabold leading-[.98] tracking-[-0.07em] sm:text-7xl">
                Обмен, который<br />
                <span className="text-muted-foreground">не отвлекает.</span>
              </h1>
              <p className="mt-7 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
                FocusPay помогает быстро купить или продать криптовалюту с прозрачным расчётом, понятными статусами и поддержкой оператора.
              </p>
              <div className="mt-8">
                <RateTicker rates={rates} />
              </div>
              <div className="mt-9 flex flex-wrap items-center gap-3">
                <Button size="lg" asChild>
                  <a href="#exchange">Рассчитать обмен<ArrowRight data-icon="inline-end" /></a>
                </Button>
                <Button size="lg" variant="outline" asChild>
                  <a href="#process">Посмотреть процесс<ChevronDown data-icon="inline-end" /></a>
                </Button>
              </div>
              <div className="mt-10 flex flex-wrap gap-x-7 gap-y-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-2"><Check data-icon="inline-start" className="text-foreground" />Без скрытых комиссий</span>
                <span className="inline-flex items-center gap-2"><Check data-icon="inline-start" className="text-foreground" />Живой оператор</span>
              </div>
            </motion.div>
            <motion.div className="min-w-0" initial={{ opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.08 }}>
              <ExchangeWidget rates={rates} />
            </motion.div>
          </div>
        </section>

        <section id="process" className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <div className="grid gap-10 lg:grid-cols-[.7fr_1.3fr]">
            <Reveal>
              <p className="text-xs font-semibold uppercase tracking-[.18em] text-muted-foreground">Простой процесс</p>
              <h2 className="mt-4 max-w-md text-3xl font-bold tracking-tight sm:text-4xl">Всё важное видно с первого взгляда.</h2>
              <p className="mt-4 max-w-md leading-7 text-muted-foreground">
                Мы убрали лишние шаги и оставили только те, которые помогают завершить обмен спокойно.
              </p>
            </Reveal>
            <div className="grid gap-3 sm:grid-cols-3">
              <Reveal delay={0.05}><Step number="01" title="Рассчитайте" text="Выберите актив, направление и сумму." /></Reveal>
              <Reveal delay={0.12}><Step number="02" title="Подтвердите" text="Проверьте курс и оставьте реквизиты." /></Reveal>
              <Reveal delay={0.19}><Step number="03" title="Получите" text="Следите за статусом до завершения." /></Reveal>
            </div>
          </div>
        </section>

        <ReviewsSection />

        <section id="security" className="border-y border-border bg-muted/30">
          <div className="mx-auto grid max-w-7xl items-start gap-8 px-4 py-16 sm:px-6 lg:grid-cols-[.8fr_1.2fr] lg:px-8">
            <Reveal>
              <h2 className="text-3xl font-bold tracking-tight">Спокойствие в каждой заявке.</h2>
              <p className="mt-4 max-w-md leading-7 text-muted-foreground">
                Статусы, реквизиты и сообщения собраны в одном потоке. Система не просит переводить средства до создания заявки.
              </p>
              <div className="grid-paper relative mt-8 flex aspect-[1.9] w-full items-center justify-center overflow-hidden rounded-xl border border-border bg-card">
                <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_40%,var(--muted),transparent_70%)]" />
                <div className="relative flex size-16 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lg shadow-foreground/10">
                  <ShieldCheck className="size-8" />
                </div>
              </div>
            </Reveal>
            <div className="grid gap-3 sm:auto-rows-fr sm:grid-cols-2">
              {[
                { icon: WalletCards, title: "Понятные реквизиты", text: "Способ оплаты и сумма отображаются до подтверждения." },
                { icon: Sparkles, title: "Живой статус", text: "Оператор видит заявку и может ответить в чате." },
                { icon: ShieldCheck, title: "Данные под защитой", text: "Реквизиты и переписка доступны только вам и вашему оператору." },
                { icon: Copy, title: "История операций", text: "Номер заявки остаётся у вас для проверки." },
              ].map((f, i) => (
                <Reveal key={f.title} delay={0.05 * i} className="h-full">
                  <Feature icon={f.icon} title={f.title} text={f.text} />
                </Reveal>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <Brand compact />
        <div className="flex flex-wrap items-center gap-5">
          <span>© {new Date().getFullYear()} FocusPay</span>
          <a className="hover:text-foreground" href="mailto:support@focuspay.org">Поддержка</a>
        </div>
      </footer>
    </div>
  );
}

function Step({ number, title, text }: { number: string; title: string; text: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="font-mono text-xs text-muted-foreground">{number}</div>
      <h3 className="mt-10 font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{text}</p>
    </div>
  );
}
function Feature({ icon: Icon, title, text }: { icon: typeof ShieldCheck; title: string; text: string }) {
  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-card p-5">
      <div className="flex size-9 items-center justify-center rounded-lg bg-muted text-foreground">
        <Icon className="size-[18px]" />
      </div>
      <h3 className="mt-4 font-semibold">{title}</h3>
      <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{text}</p>
    </div>
  );
}
