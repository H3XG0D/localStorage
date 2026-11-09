import { api } from "@/lib/api";

export interface TransferReceipt {
  id: number;
  recipient_label: string;
  amount_rub: number;
  fee_rub: number;
  net_rub: number;
}

export function quoteTransfer(amount: number): { fee: number; net: number } | null {
  if (!Number.isFinite(amount) || amount < 100) return null;
  const fee = Math.round(amount * 0.1 * 100) / 100;
  const net = Math.round((amount - fee) * 100) / 100;
  if (net <= 0) return null;
  return { fee, net };
}

export function sendTransfer(recipient: string, amount_rub: number) {
  return api<TransferReceipt>("/user/transfer", { method: "POST", body: { recipient, amount_rub } });
}
