import { useEffect, useRef, useState } from "react";
import { apiAssetUrl } from "@/panel/lib/mediaUrl";

type Props = {
  avatarUrl?: string | null;
  name?: string | null;
  username?: string | null;
  userId?: number | null;
  size?: "sm" | "md";
  className?: string;
};

const sizes = {
  sm: "w-8 h-8 text-xs",
  md: "w-10 h-10 text-sm",
};

function initials(name?: string | null, username?: string | null, userId?: number | null): string {
  const src = (name || username || "").trim().replace(/^@/, "");
  if (src) {
    const parts = src.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return src.slice(0, 2).toUpperCase();
  }
  if (userId) return String(userId).slice(-2);
  return "?";
}

function assetPath(url: string | null): string | null {
  if (!url) return null;
  const q = url.indexOf("?");
  return q >= 0 ? url.slice(0, q) : url;
}

export function BuyerAvatar({
  avatarUrl,
  name,
  username,
  userId,
  size = "md",
  className = "",
}: Props) {
  const incoming = apiAssetUrl(avatarUrl);
  const [src, setSrc] = useState<string | null>(incoming);
  const [failed, setFailed] = useState(false);
  const pathRef = useRef<string | null>(assetPath(incoming));
  const sz = sizes[size];

  useEffect(() => {
    const nextPath = assetPath(incoming);
    if (!incoming) {
      pathRef.current = null;
      setSrc(null);
      setFailed(false);
      return;
    }
    // Access tokens in the query change every list refresh; keep the first URL
    // (still valid for days) so the thread list does not refetch every avatar.
    if (nextPath !== pathRef.current) {
      pathRef.current = nextPath;
      setSrc(incoming);
      setFailed(false);
    }
  }, [incoming]);

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        className={`${sz} rounded-full object-cover ring-1 ring-white/10 shrink-0 bg-black/40 ${className}`}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <span
      className={`${sz} rounded-full shrink-0 inline-flex items-center justify-center font-semibold bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/30 ${className}`}
    >
      {initials(name, username, userId)}
    </span>
  );
}
