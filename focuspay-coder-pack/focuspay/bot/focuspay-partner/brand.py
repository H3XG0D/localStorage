"""Фирменный баннер Focus Pay (готовое видео бренда) + персональный промокод автора и озвучка.

Бот берёт ваш видеофайл materials/Баннер бренда.mp4 (зелёный хромакей) и добавляет под карточкой
чёрную плашку с промокодом автора: плашка выезжает снизу, код печатается по буквам, по ней пробегает блик. Анимация и звук оригинала сохраняются, поверх подмешивается озвучка.
Координаты плашки и тайминги настраиваются в админке (раздел «Ставки и бонусы»)."""
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import animate

BASE = Path(__file__).parent
FONTS = BASE / "webapp" / "static" / "fonts"


def brand_file(materials: Path) -> Path | None:
    for name in ("Баннер бренда.mp4", "Баннер бренда.mov", "brand.mp4"):
        p = materials / name
        if p.exists():
            return p
    return None


def probe(path: Path) -> dict:
    """Размер, fps, длительность и наличие звука — через ffmpeg -i."""
    out = subprocess.run([animate.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 6.0
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    w, h = (int(v.group(1)), int(v.group(2))) if v else (1920, 1080)
    f = re.search(r"([\d.]+) fps", out)
    fps = float(f.group(1)) if f else 30.0
    return {"w": w, "h": h, "fps": fps if 10 <= fps <= 120 else 30.0, "dur": dur, "audio": "Audio:" in out}


def _font(size: int, bold=True):
    for name in (("Manrope-Bold.ttf", "Manrope[wght].ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf") if bold else
                 ("Manrope-Medium.ttf", "Manrope[wght].ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf")):
        p = FONTS / name
        if p.exists():
            f = ImageFont.truetype(str(p), size)
            if "wght" in name:
                try:
                    f.set_variation_by_axes([700 if bold else 500])
                except Exception:
                    pass
            return f
    return ImageFont.load_default()


def _pill_frame(t: float, pw: int, ph: int, code: str, t_out: float | None, slide: int = 0) -> Image.Image:
    """Кадр плашки промокода (регион pw × (ph+slide)). t — секунды от появления."""
    S = 2
    W, H, SL = pw * S, ph * S, slide * S
    img = Image.new("RGBA", (W, H + SL), (0, 0, 0, 0))
    p_in = animate.ease_out(animate.prog(t, 0, .45))
    a_out = 1 - animate.ease_in(animate.prog(t, t_out, .3)) if t_out is not None else 1
    a = animate.clamp(p_in * 1.4) * a_out
    if a <= 0:
        return img.resize((pw, ph + slide))
    oy = SL * (1 - p_in)                                         # выезжает снизу вверх
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = H / 2
    d.rounded_rectangle([0, oy, W - 1, oy + H - 1], radius=r, fill=(0, 0, 0, 255))
    f_lab, f_code = _font(int(H * .40), False), _font(int(H * .52), True)
    label = "Промокод:"
    lw = d.textlength(label + "  ", font=f_lab)
    shown = code[:int(len(code) * animate.clamp(animate.prog(t, .35, .5)))]
    total = lw + d.textlength(code, font=f_code)
    x0 = (W - total) / 2
    d.text((x0, oy + H / 2), label, font=f_lab, fill=(170, 176, 174, 255), anchor="lm")
    d.text((x0 + lw, oy + H / 2), shown, font=f_code, fill=(255, 255, 255, 255), anchor="lm")
    if len(shown) < len(code) or ((t % .9) < .45 and t < 2.4):
        cx = x0 + lw + d.textlength(shown, font=f_code) + 4 * S
        d.rectangle([cx, oy + H * .27, cx + 2.6 * S, oy + H * .73], fill=(255, 255, 255, 255))
    sh = (t - 1.2) % 3.0                                           # блик раз в 3 секунды
    if t > 1.2 and sh < .65:
        band = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        hx = -W * .15 + (W * 1.3) * animate.ease_inout(sh / .65)
        ImageDraw.Draw(band).polygon([(hx, oy), (hx + H * .9, oy), (hx + H * .3, oy + H), (hx - H * .6, oy + H)], fill=(255, 255, 255, 55))
        m = Image.new("L", layer.size, 0)
        ImageDraw.Draw(m).rounded_rectangle([0, oy, W - 1, oy + H - 1], radius=r, fill=255)
        band.putalpha(Image.composite(band.getchannel("A"), Image.new("L", layer.size, 0), m))
        layer.alpha_composite(band)
    if a < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    img.alpha_composite(layer)
    return img.resize((pw, ph + slide), Image.LANCZOS)


def render(src: Path, out: Path, code: str, cfg: dict, voice: Path | None = None, preset: str = "veryfast",
           max_dur: float | None = None) -> Path:
    """cfg: x0,y0,x1,y1 — доли кадра, где стоит плашка промокода; t_from, t_to (сек, 0 — до конца); voice_at (сек)."""
    info = probe(src)
    W, H, dur = info["w"], info["h"], info["dur"]
    fps = min(info["fps"], 30.0)                    # 30 к/с хватает для соцсетей и вдвое быстрее сборка
    if max_dur:
        dur = min(dur, max_dur)
    x0, y0 = int(cfg["x0"] * W), int(cfg["y0"] * H)
    pw, ph = int((cfg["x1"] - cfg["x0"]) * W), int((cfg["y1"] - cfg["y0"]) * H)
    slide = max(0, min(int(ph * .35), H - (y0 + ph)))              # запас под «выезд» снизу
    t_from = float(cfg.get("t_from", 1.6))
    t_to = float(cfg.get("t_to", 0)) or None
    frames = int(math.ceil(dur * fps))
    cmd = [animate.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{pw}x{ph + slide}", "-r", f"{fps}", "-i", "-"]
    fc = f"[0:v]fps={fps}[base];[base][1:v]overlay={x0}:{y0}:eof_action=pass:format=auto,format=yuv420p[v]"
    amap = []
    if voice and voice.exists():
        cmd += ["-i", str(voice)]
        dl = int(float(cfg.get("voice_at", 0.3)) * 1000)
        if info["audio"]:
            fc += f";[2:a]adelay={dl}|{dl},volume=1.0[vo];[0:a]volume=0.6[ba];[ba][vo]amix=inputs=2:duration=first:normalize=0[a]"
        else:
            fc += f";[2:a]adelay={dl}|{dl},apad[a]"
        amap = ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    elif info["audio"]:
        amap = ["-map", "0:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-filter_complex", fc, "-map", "[v]"] + amap + ["-t", f"{dur}", "-c:v", "libx264", "-crf", "19",
                                                           "-preset", preset, "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    blank = Image.new("RGBA", (pw, ph + slide), (0, 0, 0, 0)).tobytes()
    t_out_rel = (t_to - t_from) if t_to else None
    cache: dict = {}
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            t = i / fps
            if t < t_from or (t_to and t > t_to + .35):
                proc.stdin.write(blank)
                continue
            rel = t - t_from
            if rel > 2.6 and t_out_rel is None:                    # после появления кадры повторяются — кэшируем
                ph_ = (rel - 1.2) % 3.0
                key = round(ph_ * fps) if ph_ < .65 else -1
                if key not in cache:
                    cache[key] = _pill_frame(rel, pw, ph, code, None, slide).tobytes()
                proc.stdin.write(cache[key])
            else:
                proc.stdin.write(_pill_frame(rel, pw, ph, code, t_out_rel, slide).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg: не удалось собрать фирменный баннер")
    return out
