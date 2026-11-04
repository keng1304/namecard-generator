#!/usr/bin/env python3
"""講者字卡（名卡／lower third）產生器 — 每人一張透明 PNG，疊在 Premiere 外框上方即對齊。

版型在 presets.json，字體家族在 fonts.json，兩個都可以直接加。
顏色、字體、位置都能從指令列覆寫，不用改版型。

常用：
  python3 namecard_gen.py --list                                  # 看有哪些版型、字體
  python3 namecard_gen.py --demo                                  # 所有版型各出一張，拼成 preview/presets.png
  python3 namecard_gen.py names.csv out/ --preset navy-orange       # CSV 批次（欄位：序,類別,單位,姓名,職稱，可加 版位）
  python3 namecard_gen.py --org 範例科技 --name 陳大文 --title 執行長 out/ --preset glass-dark --accent '#FF5A5F'
  python3 namecard_gen.py names.csv out/ --preset minimal-light --font genseki --pos 120,840 --canvas 3840x2160

CSV 姓名留空＝只寫單位（Pitch 團隊常用）。版位欄可填 pitch／lower-third／center-bottom 或 x,y，逐列覆寫。
"""
import argparse, csv, json, os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIRS = [os.path.join(HERE, 'fonts'), os.path.expanduser('~/Library/Fonts'), '/Library/Fonts']
BASE_W, BASE_H = 1920, 1080
# 基準畫布 1920×1080 上的卡片左上角；4K 等其他畫布等比放大
ANCHORS = {'pitch': (1451, 785), 'lower-third': (280, 776), 'lower-third-wide': (120, 900)}
ANCHORS['single'] = ANCHORS['lower-third']  # 別名：致詞位


def load(name):
    with open(os.path.join(HERE, name), encoding='utf-8') as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith('_')}


def rgba(h):
    h = h.lstrip('#')
    if len(h) not in (6, 8):
        sys.exit(f'顏色格式錯誤：#{h}（要 #RRGGBB 或 #RRGGBBAA）')
    v = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
    return tuple(v + [255] * (4 - len(v)))


class Fonts:
    """把家族名或單一字型檔解析成 B／M／R 三個字重。"""
    def __init__(self, spec, families):
        if spec in families:
            self.files = {w: self._find(families[spec][w]) for w in ('B', 'M', 'R')}
        elif os.path.isfile(os.path.expanduser(spec)):
            p = (os.path.expanduser(spec), 0)
            self.files = {'B': p, 'M': p, 'R': p}
        else:
            sys.exit(f'找不到字體「{spec}」：請用 fonts.json 的家族名（{", ".join(families)}）或字型檔路徑')
        self.cache = {}

    @staticmethod
    def _find(entry):
        fn, idx = (entry, 0) if isinstance(entry, str) else entry
        for d in FONT_DIRS:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                return (p, idx)
        sys.exit(f'字型檔 {fn} 沒裝：放進 {FONT_DIRS[0]}/ 或安裝到系統字型')

    def missing(self, text):
        """回傳三個字重裡缺字的清單；沒裝 fontTools 就不檢查。"""
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            return []
        if not hasattr(self, '_cmaps'):
            self._cmaps = {w: set(TTFont(p, fontNumber=i).getBestCmap()) for w, (p, i) in self.files.items()}
        return sorted({ch for ch in text if not ch.isspace() and any(ord(ch) not in m for m in self._cmaps.values())})

    def get(self, weight, size):
        key = (weight, size)
        if key not in self.cache:
            p, idx = self.files[weight]
            self.cache[key] = ImageFont.truetype(p, size, index=idx)
        return self.cache[key]

    def fit(self, draw, text, weight, size, maxw, minsize=14):
        while size > minsize:
            f = self.get(weight, size)
            if draw.textlength(text, font=f) <= maxw:
                return f
            size -= 1
        return self.get(weight, minsize)


def render(org, name, title, P, fonts, canvas=(BASE_W, BASE_H), pos=None):
    s = canvas[0] / BASE_W
    S = lambda v: max(1, round(v * s)) if v else 0  # 0 要保持 0（否則 radius 0 會變成 1 的圓角）
    W, H, R, BAR = S(P['w']), S(P['h']), S(P.get('radius', 0)), S(P.get('bar', 0)) if P.get('bar') else 0
    c = {k: rgba(v) for k, v in P['colors'].items()}
    sz = {k: S(v) for k, v in P['size'].items()}
    pos = pos or P.get('anchor', 'lower-third')
    if pos == 'center-bottom':
        x, y = (canvas[0] - W) // 2, canvas[1] - H - S(90)
    elif pos in ANCHORS:
        x, y = (S(v) for v in ANCHORS[pos])
    else:
        try:
            x, y = (S(int(v)) for v in str(pos).split(','))
        except ValueError:
            sys.exit(f'位置「{pos}」看不懂：用 {", ".join(list(ANCHORS) + ["center-bottom"])} 或 x,y（以 1920×1080 為基準）')
    im = Image.new('RGBA', canvas, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = [x, y, x + W - 1, y + H - 1]
    if R:
        d.rounded_rectangle(box, R, fill=c['bg'])
    else:
        d.rectangle(box, fill=c['bg'])
    lay = P['layout']

    def name_title(tx, ny, maxw, name_col, title_col, name_share=0.62):
        fn = fonts.fit(d, name, 'B', sz['name'], maxw * name_share)
        d.text((tx, ny), name, font=fn, fill=name_col)
        nw = d.textlength(name, font=fn)
        if title:
            ft = fonts.fit(d, title, 'R', sz['title'], maxw - nw - S(14))
            nb = d.textbbox((tx, ny), name, font=fn)[3]
            tb = d.textbbox((0, 0), title, font=ft)[3]
            d.text((tx + nw + S(14), nb - tb), title, font=ft, fill=title_col)  # 職稱與姓名底線對齊
        return fn, nw

    def single(text, tx, maxw, col, top=y, height=H):
        f = fonts.fit(d, text, 'B', S(32), maxw)
        bb = d.textbbox((0, 0), text, font=f)
        d.text((tx, top + (height - (bb[3] - bb[1])) / 2 - bb[1]), text, font=f, fill=col)

    if lay == 'bar':
        if BAR:
            d.rectangle([x, y, x + BAR - 1, y + H - 1], fill=c['accent'])
        tx, maxw = x + BAR + S(18), W - BAR - S(36)
        if not name:
            single(org, tx, maxw, c['name'])
        else:
            d.text((tx, y + S(14)), org, font=fonts.fit(d, org, 'M', sz['org'], maxw), fill=c['org'])
            d.line([tx, y + S(52), x + W - S(18), y + S(52)], fill=c['rule'], width=S(1))
            name_title(tx, y + S(62), maxw, c['name'], c['title'])
    elif lay in ('underline', 'pill'):
        pad = S(24) if lay == 'underline' else S(30)
        tx, maxw = x + pad, W - pad * 2
        if not name:
            single(org, tx, maxw, c['name'])
        else:
            otx = tx
            if lay == 'pill':  # 單位前加一顆強調色圓點
                r = S(5)
                d.ellipse([tx, y + S(25) - r, tx + 2 * r, y + S(25) + r], fill=c['accent'])
                otx = tx + 2 * r + S(10)
            d.text((otx, y + S(12)), org, font=fonts.fit(d, org, 'M', sz['org'], maxw - (otx - tx)), fill=c['org'])
            fn, nw = name_title(tx, y + S(46), maxw, c['name'], c['title'])
            if lay == 'underline':
                ly = y + H - S(16)
                d.rectangle([tx, ly, tx + nw, ly + S(3) - 1], fill=c['rule'])
    elif lay == 'block':
        band = BAR or S(40)
        d.rectangle([x, y, x + W - 1, y + band - 1], fill=c['accent'])
        tx, maxw = x + S(20), W - S(40)
        if not name:
            single(org, tx, maxw, c['org'], top=y, height=band)
        else:
            f = fonts.fit(d, org, 'M', sz['org'], maxw)
            bb = d.textbbox((0, 0), org, font=f)
            d.text((tx, y + (band - (bb[3] - bb[1])) / 2 - bb[1]), org, font=f, fill=c['org'])
            name_title(tx, y + band + S(18), maxw, c['name'], c['title'])
    elif lay == 'ticker':
        blk = BAR or S(260)
        d.rectangle([x, y, x + blk - 1, y + H - 1], fill=c['accent'])
        if not name:
            single(org, x + blk + S(22), W - blk - S(44), c['org'])
        else:
            single(name, x + S(22), blk - S(44), c['name'])
            rx, rw = x + blk + S(22), W - blk - S(44)
            d.text((rx, y + S(14)), org, font=fonts.fit(d, org, 'M', sz['org'], rw), fill=c['org'])
            if title:
                d.text((rx, y + S(52)), title, font=fonts.fit(d, title, 'R', sz['title'], rw), fill=c['title'])
            d.rectangle([x + blk, y + H - S(4), x + W - 1, y + H - 1], fill=c['rule'])
    else:
        sys.exit(f'版面型態「{lay}」不認得：bar／underline／pill／block／ticker')
    return im


def build_preset(args, presets):
    if args.preset not in presets:
        sys.exit(f'沒有版型「{args.preset}」：{", ".join(presets)}')
    P = json.loads(json.dumps(presets[args.preset]))
    for k in ('bg', 'accent', 'org', 'name', 'title', 'rule'):
        v = getattr(args, f'{k}_color' if k not in ('bg', 'accent') else k)
        if v:
            P['colors'][k] = v
    if args.accent and not args.rule_color and P['layout'] in ('underline', 'ticker'):
        P['colors']['rule'] = args.accent
    if args.accent and not args.org_color and P['colors']['org'].upper() == presets[args.preset]['colors']['accent'].upper():
        P['colors']['org'] = args.accent  # 單位原本跟強調色同色的版型，換強調色時一起換
    if args.text_scale != 1:
        P['size'] = {k: round(v * args.text_scale) for k, v in P['size'].items()}
    return P


def demo(presets, families, canvas):
    os.makedirs(os.path.join(HERE, 'preview'), exist_ok=True)
    tw, th = 960, 540
    sheet = Image.new('RGB', (tw * 2, th * ((len(presets) + 1) // 2)), (40, 40, 40))
    for i, (key, P) in enumerate(presets.items()):
        bg = Image.new('RGBA', canvas, (70, 82, 96, 255))
        g = ImageDraw.Draw(bg)  # 假畫面：斜向漸層，看得出半透明效果
        for yy in range(0, canvas[1], 6):
            g.rectangle([0, yy, canvas[0], yy + 5], fill=(60 + yy * 60 // canvas[1], 72 + yy * 40 // canvas[1], 96, 255))
        card = render('範例科技股份有限公司', '陳大文', '創辦人暨執行長', P, Fonts(P['font'], families), canvas)
        bg.alpha_composite(card)
        ImageDraw.Draw(bg).text((40, 30), f'{key}｜{P["label"]}', font=Fonts(P['font'], families).get('M', 34), fill=(255, 255, 255, 255))
        sheet.paste(bg.convert('RGB').resize((tw, th)), ((i % 2) * tw, (i // 2) * th))
    out = os.path.join(HERE, 'preview', 'presets.png')
    sheet.save(out)
    print('✓', out)


def main():
    ap = argparse.ArgumentParser(description='講者字卡產生器', formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('csv', nargs='?', help='名單 CSV（序,類別,單位,姓名,職稱[,版位]）；單張模式可省略')
    ap.add_argument('out', nargs='?', help='輸出資料夾')
    ap.add_argument('--preset', default='navy-orange')
    ap.add_argument('--font', help='fonts.json 家族名或字型檔路徑（覆寫版型字體）')
    ap.add_argument('--accent'); ap.add_argument('--bg')
    ap.add_argument('--org-color'); ap.add_argument('--name-color'); ap.add_argument('--title-color'); ap.add_argument('--rule-color')
    ap.add_argument('--text-scale', type=float, default=1.0, help='字級整體縮放，例 0.9')
    ap.add_argument('--pos', help='pitch／lower-third／lower-third-wide／center-bottom 或 x,y（1920×1080 基準）')
    ap.add_argument('--canvas', default='1920x1080', help='輸出畫布，例 3840x2160（等比放大）')
    ap.add_argument('--org'); ap.add_argument('--name', default=''); ap.add_argument('--title', default='')
    ap.add_argument('--prefix', default='字卡_講者名卡'); ap.add_argument('--date', default=''); ap.add_argument('--ver', default='1')
    ap.add_argument('--list', action='store_true'); ap.add_argument('--demo', action='store_true')
    ap.add_argument('--allow-missing', action='store_true', help='缺字仍照出（預設擋下）')
    a = ap.parse_args()
    presets, families = load('presets.json'), load('fonts.json')
    canvas = tuple(int(v) for v in a.canvas.lower().split('x'))
    if a.list:
        print('版型：'); [print(f'  {k:<14} {v["label"]}') for k, v in presets.items()]
        print('字體：'); [print(f'  {k}') for k in families]
        return
    if a.demo:
        return demo(presets, families, canvas)
    P = build_preset(a, presets)
    fonts = Fonts(a.font or P['font'], families)
    if a.org:  # 單張模式：out 可放在第一個位置參數
        rows = [{'序': '1', '類別': '', '單位': a.org, '姓名': a.name, '職稱': a.title}]
        out = a.out or a.csv
    else:
        if not (a.csv and a.out):
            ap.error('要給 CSV 與輸出資料夾，或用 --org 單張模式')
        rows = list(csv.DictReader(open(a.csv, encoding='utf-8-sig')))
        out = a.out
    os.makedirs(out, exist_ok=True)
    date = a.date or __import__('datetime').date.today().strftime('%Y%m%d')
    miss = fonts.missing(''.join(''.join((r.get(k) or '') for k in ('單位', '姓名', '職稱')) for r in rows))
    if miss:
        print(f'⚠️ 字體缺字，會印成方塊：{"".join(miss)} → 換 --font（例 genseki、noto-sans-tc）', file=sys.stderr)
        if not a.allow_missing:
            sys.exit(1)
    made = []
    for i, r in enumerate(rows, 1):
        org, name, title = ((r.get(k) or '').strip() for k in ('單位', '姓名', '職稱'))
        if not org and not name:
            continue
        im = render(org, name, title, P, fonts, canvas, a.pos or (r.get('版位') or '').strip() or None)
        label = name.split(' ')[0].split('(')[0] or org.replace('股份有限公司', '').replace('有限公司', '')
        seq = int(r.get('序') or i)
        fn = f"{a.prefix}{(r.get('類別') or '').strip()}{label}_{seq:02d}_{date}_v{a.ver}.png"
        im.save(os.path.join(out, fn)); made.append(fn)
    print(f'{len(made)} 張（版型 {a.preset}，畫布 {canvas[0]}×{canvas[1]}）→ {out}')
    for m in made:
        print(' ', m)


if __name__ == '__main__':
    main()
