// Two-column auth layout: a dark brand panel (with subtle noise material) and a
// content column for the form. Shared by login / register / forgot.
import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";

export function AuthShell({
  title,
  subtitle,
  children,
  hideSiteLink,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  hideSiteLink?: boolean;
}) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_.95fr]">
      <section className="noise hidden flex-col justify-between bg-primary p-8 text-primary-foreground lg:flex lg:p-12">
        <div>
          <Brand className="text-primary-foreground" />
          <div className="mt-28 max-w-xl">
            <p className="font-mono text-xs uppercase tracking-[.2em] text-primary-foreground/60">FocusPay / exchange</p>
            <h1 className="mt-5 text-5xl font-extrabold leading-[.98] tracking-[-.06em]">
              Спокойный
              <br />
              обмен.
            </h1>
            <p className="mt-7 max-w-md text-base leading-7 text-primary-foreground/65">
              Курс, статусы и поддержка оператора — в одном понятном пространстве.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-primary-foreground/55">
          <ShieldCheck />
          <span>Защищённая сессия</span>
        </div>
      </section>

      <section className="flex min-h-screen flex-col bg-background p-5 sm:p-8">
        <div className={`flex items-center ${hideSiteLink ? "justify-end" : "justify-between"}`}>
          {!hideSiteLink && (
            <Link to="/" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
              ← На сайт
            </Link>
          )}
          <ThemeToggle />
        </div>
        <div className="m-auto w-full max-w-md">
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
            <div className="mb-8 lg:hidden">
              <Brand />
            </div>
            <div className="mb-6">
              <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{subtitle}</p>
            </div>
            {children}
          </motion.div>
        </div>
      </section>
    </main>
  );
}
