import type { ReactNode } from "react";
import { FOCUS_OPERATOR_AVATAR, FOCUS_OPERATOR_NAME } from "@/panel/lib/focusOperator";
import { formatChatMessageTime } from "@/panel/lib/chatMessageTime";
import { BuyerAvatar } from "@/panel/ui/BuyerAvatar";
import { ChatMessageContent, type ChatMessageContentModel } from "@/panel/ui/ChatMessageContent";

export type ChatPeerAvatar = {
  avatarUrl?: string | null;
  name?: string | null;
  username?: string | null;
  userId?: number | null;
};

type Props = {
  message: ChatMessageContentModel;
  variant: "buyer" | "admin";
  align?: "start" | "end";
  peer?: ChatPeerAvatar | null;
  children?: ReactNode;
};

function BubbleTime({ iso, tone }: { iso: string | null | undefined; tone: "light" | "dark" | "amber" }) {
  const label = formatChatMessageTime(iso);
  if (!label) return null;
  const toneClass =
    tone === "light" ? "text-gray-500" : tone === "amber" ? "text-black/55" : "text-gray-400";
  return (
    <span className={`text-[11px] leading-none mt-1.5 block text-right ${toneClass}`}>{label}</span>
  );
}

export function FocusOperatorChatBubble({ message, variant, align = "start", peer, children }: Props) {
  const isSupport = message.sender_role === "admin";
  const isEnd = align === "end";

  if (!isSupport) {
    const tone = isEnd ? "light" : "dark";
    return (
      <div className={`flex gap-2 max-w-full ${isEnd ? "flex-row-reverse justify-start" : "justify-start"}`}>
        <BuyerAvatar
          avatarUrl={peer?.avatarUrl}
          name={peer?.name}
          username={peer?.username}
          userId={peer?.userId}
          size="sm"
        />
        <div
          className={`min-w-0 max-w-[calc(100%-2.5rem)] rounded-2xl px-3 py-2 text-sm ${
            isEnd ? "bg-white text-black rounded-br-md" : "bg-white/10 text-gray-100 rounded-bl-md"
          }`}
        >
          {children ?? <ChatMessageContent message={message} variant={variant} />}
          <BubbleTime iso={message.created_at} tone={tone} />
        </div>
      </div>
    );
  }

  const bubbleTone = isEnd ? "amber" : "dark";

  return (
    <div className={`flex gap-2 max-w-full ${isEnd ? "flex-row-reverse justify-start" : "justify-start"}`}>
      <img
        src={FOCUS_OPERATOR_AVATAR}
        alt=""
        className="w-9 h-9 rounded-full object-cover ring-1 ring-white/15 shrink-0"
      />
      <div className={`min-w-0 max-w-[calc(100%-2.75rem)] flex flex-col ${isEnd ? "items-end" : "items-start"}`}>
        <span className="text-[11px] text-gray-500 mb-0.5 px-1">{FOCUS_OPERATOR_NAME}</span>
        <div
          className={`rounded-2xl px-3 py-2 text-sm ${
            isEnd ? "bg-amber-500/90 text-black rounded-br-md" : "bg-white/10 text-gray-100 rounded-bl-md"
          }`}
        >
          {children ?? <ChatMessageContent message={message} variant={variant} />}
          <BubbleTime iso={message.created_at} tone={bubbleTone} />
        </div>
      </div>
    </div>
  );
}
