import { useEffect, useRef } from "react";
import { hideMainButton, isCasinoMiniApp, showMainButton } from "./telegram";

export function TelegramMainButton({
  text,
  onClick,
  visible = true,
}: {
  text: string;
  onClick: () => void;
  visible?: boolean;
}) {
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    if (!isCasinoMiniApp() || !visible) {
      hideMainButton();
      return;
    }
    const handler = () => clickRef.current();
    showMainButton(text, handler);
    return () => hideMainButton();
  }, [text, visible]);

  return null;
}
