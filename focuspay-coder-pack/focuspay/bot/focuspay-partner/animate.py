"""Анимированные баннеры Focus Pay поверх ролика.

1) TOP  — маленький баннер вверху кадра на весь ролик (бесшовный цикл).
2) MID  — баннер в середине ролика: карточка 960×540 = 25% площади кадра, 6 сек, со звуком.

Каждый рендерится на весь кадр 1080×1920 в двух вариантах:
  • MP4 на синем фоне — для CapCut (Наложение → Удалить фон → Хромакей → выбрать синий);
  • MOV с прозрачностью (кодек PNG) — для монтажа на компьютере (Premiere, Final Cut, DaVinci, CapCut ПК).
ffmpeg берётся из пакета imageio-ffmpeg (ставится через pip) или из системы."""
import math
import random
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).parent
FONT_B = str(BASE / "webapp" / "static" / "fonts" / "DejaVuSans-Bold.ttf")
FONT_R = str(BASE / "webapp" / "static" / "fonts" / "DejaVuSans.ttf")
FPS = 30
W, H = 1080, 1920
SS = 2                                   # суперсэмплинг — гладкие края
LIME = (198, 255, 61)
WHITE = (255, 255, 255)
GREY = (168, 176, 172)
INK = (10, 11, 13)
KEY = (0, 60, 255)                       # синий хромакей: в баннере нет синих цветов
TOP_Y = 205                              # ниже интерфейса TikTok/Reels сверху
MID_BOX = (60, 690, 1020, 1230)          # 960×540 по центру кадра


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def audio_duration(path: Path) -> float:
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


@lru_cache(maxsize=64)
def font(size, bold=True):
    return ImageFont.truetype(FONT_B if bold else FONT_R, size)


def clamp(x): return max(0.0, min(1.0, x))
def prog(t, a, d): return clamp((t - a) / d)
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_in(x): x = clamp(x); return x ** 3
def ease_inout(x): x = clamp(x); return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def spring(x, k=7.0, damp=4.5):
    """Пружина: быстро к 1 с затухающим перелётом."""
    x = clamp(x)
    return 1 - math.exp(-damp * x) * math.cos(k * x) if x < 1 else 1.0


BLOCKS = ((62, 0, 122, 64), (0, 54, 76, 72), (30, 124, 82, 64), (0, 176, 62, 62))


def draw_mark(d, cx, cy, h, appear=1.0, stagger_t=None, fill=WHITE):
    """Знак F. stagger_t — время сборки (блоки выезжают по очереди), None — сразу целый."""
    k = h / 238
    ox, oy = cx - 184 * k / 2, cy - h / 2
    dirs = ((1, -1), (-1, 0), (1, 1), (-1, 1))
    for i, (rx, ry, rw, rh) in enumerate(BLOCKS):
        p = 1.0 if stagger_t is None else spring(prog(stagger_t, i * 0.09, 0.6))
        if p <= 0.001:
            continue
        off = (1 - min(p, 1)) * 60 * k
        dx, dy = dirs[i][0] * off, dirs[i][1] * off
        a = int(255 * clamp(p) * appear)
        d.rounded_rectangle([ox + rx * k + dx, oy + ry * k + dy, ox + (rx + rw) * k + dx, oy + (ry + rh) * k + dy],
                            radius=13 * k, fill=fill + (a,))


def plane_icon(d, x, y, s, fill):
    """Простой значок «бумажный самолётик»."""
    d.polygon([(x, y + s * .45), (x + s, y), (x + s * .62, y + s), (x + s * .45, y + s * .62)], fill=fill)
    d.polygon([(x + s * .45, y + s * .62), (x + s, y), (x + s * .38, y + s * .55)], fill=tuple(int(c * .75) for c in fill[:3]) + fill[3:])


def glow_layer(size, box, color, radius, alpha):
    g = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(g).rounded_rectangle(box, radius=radius, fill=color + (alpha,))
    return g.filter(ImageFilter.GaussianBlur(radius * 0.9))


def border_comet(d, box, r, pos, length, width, color):
    """Светящаяся «комета», бегущая по периметру скруглённой рамки. pos 0..1."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    per = 2 * (w + h)
    pts = []
    N = 90
    for j in range(N):
        s = ((pos - length * j / N) % 1) * per
        if s < w: px, py = x0 + s, y0
        elif s < w + h: px, py = x1, y0 + (s - w)
        elif s < 2 * w + h: px, py = x1 - (s - w - h), y1
        else: px, py = x0, y1 - (s - 2 * w - h)
        pts.append((px, py, 1 - j / N))
    for j in range(len(pts) - 1, 0, -1):
        (x1_, y1_, a), (x2_, y2_, _) = pts[j], pts[j - 1]
        if abs(x1_ - x2_) + abs(y1_ - y2_) > w / 4:      # разрыв на углу цикла
            continue
        d.line([(x1_, y1_), (x2_, y2_)], fill=color + (int(255 * a ** 1.4),), width=max(1, int(width * (0.6 + a))))
    hx, hy, _ = pts[0]
    rr = width * 1.6
    d.ellipse([hx - rr, hy - rr, hx + rr, hy + rr], fill=WHITE + (255,))


# ───────────────────────── 2) БАННЕР В СЕРЕДИНЕ (25% кадра) ─────────────────────────
PAD = 90                                     # запас вокруг карточки под свечение и частицы
RW, RH = (MID_BOX[2] - MID_BOX[0]) + 2 * PAD, (MID_BOX[3] - MID_BOX[1]) + 2 * PAD


@lru_cache(maxsize=1)
def _particles():
    rnd = random.Random(42)
    return [(rnd.uniform(0, 2 * math.pi), rnd.uniform(380, 820), rnd.uniform(3, 9), rnd.random() < .6,
             rnd.uniform(0, .12)) for _ in range(70)]


def mid_region(t, total, promo, exchange):
    """Возвращает RGBA-регион RW×RH (уже уменьшенный после суперсэмплинга)."""
    S = SS
    img = Image.new("RGBA", (RW * S, RH * S), (0, 0, 0, 0))
    cw, ch = (MID_BOX[2] - MID_BOX[0]) * S, (MID_BOX[3] - MID_BOX[1]) * S
    cx, cy = img.width / 2, img.height / 2
    exit_p = ease_in(prog(t, total - 0.45, 0.45))
    sc = (0.55 + 0.45 * spring(prog(t, 0.0, 0.75), 9, 5)) * (1 - 0.25 * exit_p)
    alpha = clamp(prog(t, 0, .18)) * (1 - exit_p)
    if alpha <= 0:
        return img.resize((RW, RH), Image.LANCZOS)
    bw, bh = cw * sc, ch * sc
    box = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]
    rad = 54 * S * sc
    # частицы-вспышка при появлении
    pp = prog(t, 0.05, 0.9)
    if 0 < pp < 1:
        d = ImageDraw.Draw(img)
        for ang, dist, size, lime, delay in _particles():
            q_ = ease_out(prog(pp, delay, 1 - delay))
            if q_ <= 0:
                continue
            r = dist * S * q_ * 0.85
            px, py = cx + math.cos(ang) * r, cy + math.sin(ang) * r * 0.62
            a = int(230 * (1 - q_) * alpha)
            s_ = size * S * (1 - .5 * q_)
            d.ellipse([px - s_, py - s_, px + s_, py + s_], fill=(LIME if lime else WHITE) + (a,))
    # мягкое лаймовое свечение за карточкой (дышит)
    breath = 0.75 + 0.25 * math.sin(t * 2.4)
    img.alpha_composite(glow_layer(img.size, box, LIME, int(40 * S), int(70 * alpha * breath)))
    d = ImageDraw.Draw(img)
    # тело карточки + тонкая рамка
    d.rounded_rectangle(box, radius=rad, fill=(9, 10, 12, int(242 * alpha)), outline=(58, 74, 22, int(255 * alpha)), width=2 * S)
    # светлая «стеклянная» полоса сверху
    # бегущая по рамке комета
    if alpha > .5:                                    # комета видна только на скруглённой рамке
        cl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        border_comet(ImageDraw.Draw(cl), box, rad, (t * 0.33) % 1, 0.18, 3.2 * S, LIME)
        ring = Image.new("L", img.size, 0)
        ImageDraw.Draw(ring).rounded_rectangle([box[0] - 4 * S, box[1] - 4 * S, box[2] + 4 * S, box[3] + 4 * S],
                                               radius=rad + 4 * S, outline=255, width=9 * S)
        cl.putalpha(Image.composite(cl.getchannel("A"), Image.new("L", img.size, 0), ring))
        img.alpha_composite(cl)
        d = ImageDraw.Draw(img)
    k = sc
    L = box[0] + 54 * S * k                                   # левый край контента
    # плитка логотипа со сборкой знака
    tile = [L, cy - 150 * S * k, L + 300 * S * k, cy + 150 * S * k]
    img.alpha_composite(glow_layer(img.size, tile, WHITE, int(30 * S), int(40 * alpha * ease_out(prog(t, .5, .6)))))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(tile, radius=60 * S * k, fill=(0, 0, 0, int(255 * alpha)), outline=(46, 50, 56, int(255 * alpha)), width=2 * S)
    draw_mark(d, (tile[0] + tile[2]) / 2, cy, 190 * S * k, alpha, stagger_t=t - 0.2)
    # текстовый блок справа
    TX = tile[2] + 46 * S * k
    tw_max = box[2] - 46 * S * k - TX
    # заголовок — выезд из-под маски
    p = ease_out(prog(t, .45, .55))
    if p > 0:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ty = cy - 170 * S * k
        ld.text((TX, ty + (1 - p) * 70 * S * k), "FOCUS PAY", font=font(int(78 * S * k)), fill=WHITE + (int(255 * alpha),))
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).rectangle([TX - 10, ty - 6 * S, box[2], ty + 96 * S * k], fill=255)
        layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", img.size, 0), m))
        img.alpha_composite(layer)
        d = ImageDraw.Draw(img)
    p = ease_out(prog(t, .7, .5))
    if p > 0:
        d.text((TX + (1 - p) * 30 * S, cy - 72 * S * k), "Обмен без цирка", font=font(int(40 * S * k), False),
               fill=GREY + (int(255 * alpha * p),))
    # плашка промокода: раскрывается, код печатается, по ней проходит блик
    p = ease_out(prog(t, 1.0, .55))
    if p > 0:
        label = "ПРОМОКОД" if promo else "ССЫЛКА"
        code = promo or "В ПРОФИЛЕ"
        f1, f2 = font(int(26 * S * k)), font(int(52 * S * k))
        py0 = cy + 4 * S * k
        ph = 112 * S * k
        full_w = min(tw_max, max(d.textlength(code, font=f2) + 70 * S * k, 330 * S * k))
        pw = full_w * p
        pill = [TX, py0, TX + pw, py0 + ph]
        d.rounded_rectangle(pill, radius=28 * S * k, fill=LIME + (int(255 * alpha),))
        if p > .9:
            d.text((TX + 30 * S * k, py0 + 12 * S * k), label, font=f1, fill=INK + (int(170 * alpha),))
            n = int(len(code) * clamp(prog(t, 1.35, .45)))
            shown = code[:n]
            d.text((TX + 30 * S * k, py0 + 42 * S * k), shown, font=f2, fill=INK + (int(255 * alpha),))
            if n < len(code) or (t % .8) < .4:                 # мигающий курсор
                cxp = TX + 30 * S * k + d.textlength(shown, font=f2) + 6 * S
                d.rectangle([cxp, py0 + 48 * S * k, cxp + 5 * S * k, py0 + 96 * S * k], fill=INK + (int(255 * alpha),))
            for st in (2.1, 4.1):                                # блики
                sh = prog(t, st, .55)
                if 0 < sh < 1:
                    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    hx = pill[0] + (pw + 160 * S) * ease_inout(sh) - 80 * S
                    ImageDraw.Draw(band).polygon([(hx, pill[1]), (hx + 46 * S, pill[1]), (hx + 6 * S, pill[3]), (hx - 40 * S, pill[3])],
                                                 fill=(255, 255, 255, 150))
                    m = Image.new("L", img.size, 0)
                    ImageDraw.Draw(m).rounded_rectangle(pill, radius=28 * S * k, fill=255)
                    band.putalpha(Image.composite(band.getchannel("A"), Image.new("L", img.size, 0), m))
                    img.alpha_composite(band)
                    d = ImageDraw.Draw(img)
    # строка Telegram
    p = ease_out(prog(t, 1.6, .5))
    if p > 0:
        yy = cy + 140 * S * k
        plane_icon(d, TX, yy + 4 * S * k, 34 * S * k, WHITE + (int(255 * alpha * p),))
        d.text((TX + 50 * S * k + (1 - p) * 20 * S, yy), exchange, font=font(int(36 * S * k)), fill=WHITE + (int(255 * alpha * p),))
    # прогресс-полоса внизу карточки
    pb = clamp(prog(t, .3, total - .9))
    if pb > 0:
        y1 = box[3] - 22 * S * k
        d.rounded_rectangle([box[0] + 54 * S * k, y1, box[2] - 54 * S * k, y1 + 6 * S * k], radius=3 * S, fill=(40, 44, 48, int(255 * alpha)))
        d.rounded_rectangle([box[0] + 54 * S * k, y1, box[0] + 54 * S * k + (bw - 108 * S * k) * pb, y1 + 6 * S * k],
                            radius=3 * S, fill=LIME + (int(255 * alpha),))
    return img.resize((RW, RH), Image.LANCZOS)


# ───────────────────────── 1) БАННЕР СВЕРХУ (цикл) ─────────────────────────
TW, TH = 940, 150
TPAD = 40
TRW, TRH = TW + 2 * TPAD, TH + 2 * TPAD
LOOP = 4.0


def top_region(t, promo, exchange):
    S = SS
    img = Image.new("RGBA", (TRW * S, TRH * S), (0, 0, 0, 0))
    box = [TPAD * S, TPAD * S, (TPAD + TW) * S, (TPAD + TH) * S]
    ph = (t % LOOP) / LOOP                          # фаза цикла 0..1
    breath = .5 + .5 * math.sin(2 * math.pi * ph)
    img.alpha_composite(glow_layer(img.size, box, LIME, 22 * S, int(40 + 30 * breath)))
    d = ImageDraw.Draw(img)
    rad = TH * S / 2
    d.rounded_rectangle(box, radius=rad, fill=(9, 10, 12, 238), outline=(58, 74, 22, 255), width=2 * S)
    # логотип
    lx = box[0] + 18 * S
    tile = [lx, box[1] + 18 * S, lx + 114 * S, box[3] - 18 * S]
    d.rounded_rectangle(tile, radius=57 * S, fill=(0, 0, 0, 255), outline=(46, 50, 56, 255), width=2 * S)
    draw_mark(d, (tile[0] + tile[2]) / 2, (tile[1] + tile[3]) / 2, 64 * S)
    tx = tile[2] + 26 * S
    d.text((tx, box[1] + 22 * S), "Focus Pay", font=font(44 * S), fill=WHITE + (255,))
    # статус «онлайн»
    nx = tx + d.textlength("Focus Pay", font=font(44 * S)) + 22 * S
    ny = box[1] + 48 * S
    a = int(120 + 135 * breath)
    d.ellipse([nx, ny - 9 * S, nx + 18 * S, ny + 9 * S], fill=LIME + (a,))
    rr = 9 * S + 16 * S * ph
    d.ellipse([nx + 9 * S - rr, ny - rr, nx + 9 * S + rr, ny + rr], outline=LIME + (int(160 * (1 - ph)),), width=2 * S)
    sub = f"промокод {promo} · {exchange}" if promo else f"обмен в Telegram · {exchange}"
    fs = 32
    while d.textlength(sub, font=font(fs * S)) > box[2] - tx - 40 * S and fs > 20:
        fs -= 1
    d.text((tx, box[1] + 84 * S), sub, font=font(fs * S), fill=LIME + (255,))
    # блик по всей плашке раз в цикл
    sh = prog(ph, .55, .35)
    if 0 < sh < 1:
        band = Image.new("RGBA", img.size, (0, 0, 0, 0))
        hx = box[0] + (TW * S + 300 * S) * ease_inout(sh) - 150 * S
        ImageDraw.Draw(band).polygon([(hx, box[1]), (hx + 70 * S, box[1]), (hx + 10 * S, box[3]), (hx - 60 * S, box[3])],
                                     fill=(255, 255, 255, 46))
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).rounded_rectangle(box, radius=rad, fill=255)
        band.putalpha(Image.composite(band.getchannel("A"), Image.new("L", img.size, 0), m))
        img.alpha_composite(band)
    return img.resize((TRW, TRH), Image.LANCZOS)


# ───────────────────────── звук и рендер ─────────────────────────
def _sfx(total):
    return (f"anoisesrc=d={total}:c=pink:a=0.3,highpass=f=600,lowpass=f=6000,"
            f"volume='if(between(t,0,0.55),sin(PI*t/0.55)*0.9,0)':eval=frame[wh];"
            f"sine=f=110:d={total},volume='if(between(t,0.05,0.6),0.6*exp(-7*(t-0.05)),0)':eval=frame[bm];"
            f"sine=f=1318:d={total},volume='if(gte(t,1.05),0.28*exp(-5*(t-1.05)),0)':eval=frame[d1];"
            f"sine=f=1975:d={total},volume='if(gte(t,1.12),0.18*exp(-5*(t-1.12)),0)':eval=frame[d2];"
            f"anoisesrc=d={total}:c=white:a=0.2,highpass=f=2000,"
            f"volume='if(between(t,{total - 0.45},{total}),sin(PI*(t-{total - 0.45})/0.45)*0.5,0)':eval=frame[out];"
            f"[wh][bm][d1][d2][out]amix=inputs=5:normalize=0[sfx]")


def render(kind, out: Path, promo, exchange, voice: Path | None = None, mode="key", seconds=None):
    """kind: 'mid' | 'top'.  mode: 'key' (MP4 на синем) | 'alpha' (MOV с прозрачностью)."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg не найден")
    if kind == "mid":
        total = 6.0
        if voice and voice.exists():
            total = max(6.0, audio_duration(voice) + 1.3)
        rw, rh, ox, oy = RW, RH, MID_BOX[0] - PAD, MID_BOX[1] - PAD
    else:
        total = seconds or 20.0
        rw, rh, ox, oy = TRW, TRH, (W - TRW) // 2, TOP_Y - TPAD
    frames = int(total * FPS)
    cache = {}
    bgc = "0x%02X%02X%02X" % KEY
    out.parent.mkdir(parents=True, exist_ok=True)
    # регион кладём в полный кадр через ffmpeg (быстро), фон — синий или прозрачный
    if mode == "key":
        vf = f"[0:v]format=rgba[r];color=c={bgc}:s={W}x{H}:r={FPS}:d={total}[bg];[bg][r]overlay={ox}:{oy}:shortest=1,format=yuv420p[v]"
    else:
        vf = (f"[0:v]format=rgba[r];color=c=black@0.0:s={W}x{H}:r={FPS}:d={total},format=rgba[bg];"
              f"[bg][r]overlay={ox}:{oy}:shortest=1:format=auto,format=rgba[v]")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{rw}x{rh}", "-r", str(FPS), "-i", "-"]
    amap = []
    if kind == "mid":
        fc = _sfx(total)
        if voice and voice.exists():
            cmd += ["-i", str(voice)]
            fc += ";[1:a]adelay=450|450,volume=1.0[vo];[sfx]volume=0.45[s2];[vo][s2]amix=inputs=2:normalize=0[a]"
        else:
            fc += ";[sfx]anull[a]"
        vf = vf + ";" + fc
        amap = ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-filter_complex", vf, "-map", "[v]"] + amap + ["-t", f"{total}"]
    if mode == "alpha":
        cmd += ["-c:v", "png", "-pix_fmt", "rgba", str(out)]       # MOV+PNG: прозрачность, небольшой размер
    else:
        cmd += ["-c:v", "libx264", "-crf", "19", "-preset", "veryfast", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            t = i / FPS
            if kind == "mid":
                fr = mid_region(t, total, promo, exchange)
                if mode == "key":
                    fr = keyify(fr)
            else:
                key = round((t % LOOP) * FPS)           # цикл: кадры повторяются, считаем один раз
                if key not in cache:
                    cache[key] = top_region(t % LOOP, promo, exchange)
                    if mode == "key":
                        cache[key] = keyify(cache[key])
                fr = cache[key]
            proc.stdin.write(fr.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg завершился с ошибкой")
    return out


def keyify(fr: Image.Image) -> Image.Image:
    """Для хромакея: полупрозрачное кладём на чёрное, совсем прозрачное — синий фон. Без синих ореолов."""
    a = fr.getchannel("A")
    mask = a.point(lambda v: 255 if v >= 70 else 0)
    solid = Image.new("RGBA", fr.size, (0, 0, 0, 255))
    solid.alpha_composite(fr)
    out = Image.new("RGBA", fr.size, KEY + (255,))
    out.paste(solid, (0, 0), mask)
    return out


def find_voice(folder: Path):
    return next(iter(sorted(folder.glob("Озвучка вставка*.mp3"))), None) if folder.exists() else None


if __name__ == "__main__":
    import sys
    ex = sys.argv[1] if len(sys.argv) > 1 else "@focuspay1_bot"
    mat = BASE / "materials"
    v = find_voice(mat)
    render("mid", mat / "Баннер в центре (синий фон).mp4", None, ex, v, "key")
    render("mid", mat / "Баннер в центре (прозрачный).mov", None, ex, v, "alpha")
    render("top", mat / "Баннер сверху (синий фон).mp4", None, ex, None, "key", 60)
    render("top", mat / "Баннер сверху (прозрачный).mov", None, ex, None, "alpha", 30)
    print("Готово")
