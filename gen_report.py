#!/usr/bin/env python3
"""Benchmark HTML -> Confluence-native assets (charts PNG + storage-format XHTML)."""
import json
import math
import pathlib
import re

from PIL import Image, ImageDraw, ImageFont

SRC = pathlib.Path('/home/jaeyoon/aisio/aisio/cijoe-output/artifacts/benchmark-results.html')
OUT_PNG = pathlib.Path('/tmp/benchmark-charts.png')
OUT_XHTML = pathlib.Path('/tmp/benchmark-confluence.xhtml')

html = SRC.read_text()
m = re.search(r'const datasets = (\[.*?\])\s*;\s*const rows', html, re.S)
assert m, 'datasets regex miss'
datasets = json.loads(m.group(1))
rows = [dict(r, datasetLabel=d['label']) for d in datasets for r in d['data']]
print(f'rows={len(rows)}, datasets={len(datasets)}')

UIO = '#d96b2b'
VFIO = '#2457c5'
PANEL = '#f7f9fc'
LINE = '#dce3ec'
INK = '#1e2430'
MUTED = '#6d7481'
TCK = '#cbd5e1'

FONT_DIRS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
]


def font(size, bold=False):
    cand = [p for p in FONT_DIRS if (bold == ('Bold' in pathlib.Path(p).name))] + \
           [p for p in FONT_DIRS if True]
    for p in cand:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def compact(value):
    value = float(value)
    a = abs(value)
    if a >= 1e9:
        return trimf(value / 1e9, 2) + 'G'
    if a >= 1e6:
        return trimf(value / 1e6, 2) + 'M'
    if a >= 1e3:
        return trimf(value / 1e3, 1) + 'K'
    return str(int(round(value))) if a >= 100 else ('%.1f' % value)


def trimf(v, digits):
    s = ('%.' + str(digits) + 'f') % v
    s = re.sub(r'\.0+$', '', s)
    s = re.sub(r'(\.\d*[1-9])0+$', r'\1', s)
    return s


def pct_delta(base, value):
    if not base:
        return None
    return (value - base) / base * 100.0


def chart_metric(entries, title, unit, value_for):
    cr = []
    for item in entries:
        uio = value_for(item['uio'])
        vfio = value_for(item['vfio'])
        cr.append(dict(iodepth=item['iodepth'], uio=uio, vfio=vfio,
                       delta=pct_delta(uio, vfio)))
    return dict(title=title, rw=entries[0]['rw'], iosize=entries[0]['iosize'],
                devcount=entries[0].get('devcount', 1),
                memory=entries[0].get('memory', 'host'), unit=unit,
                labels=[r['iodepth'] for r in cr],
                uio=[r['uio'] for r in cr], vfio=[r['vfio'] for r in cr],
                rows=cr)


def build_charts(items):
    groups = {}
    for it in items:
        key = (it['runner'], it.get('memory', 'host'), it['rw'],
               it['iosize'], it.get('devcount', 1))
        groups.setdefault(key, []).append(it)
    runner_order = {'xnvmeperf': 0, 'fio': 1}
    order = sorted(groups, key=lambda k: (
        str(k[1]), runner_order.get(k[0], 99), k[2], k[3], k[4]))
    charts = []
    for key in order:
        entries = sorted(groups[key], key=lambda e: e['iodepth'])
        runner = entries[0]['runner']
        charts.append(chart_metric(entries, f'{runner} IOPS', 'IOPS',
                                   lambda s: s['iops']))
        charts.append(chart_metric(entries, f'{runner} bandwidth', 'MiB/s',
                                   lambda s: s['mibs']))
        if runner != 'fio':
            continue
        charts.append(chart_metric(entries, 'fio mean latency', 'us',
                                   lambda s: s['lat_ns'] / 1000.0))
        for kk, label in [('p99_9', 'fio P99.9 latency'),
                          ('p99_99', 'fio P99.99 latency'),
                          ('p99_999', 'fio P99.999 latency')]:
            charts.append(chart_metric(entries, label, 'us',
                                       lambda s, k=kk: s['tail_lat_ns'][k] / 1000.0))
    return charts


charts = build_charts(rows)
print(f'charts={len(charts)}')
for c in charts:
    print(' ', c['title'], '|', c['memory'], c['rw'], c['iosize'],
          '| qd', c['labels'])


# ---- draw charts into one 2-column PNG ----
CW, CH = 780, 450
GAPX, GAPY = 20, 14
PAD = 22
COLS = 2
nrows = math.ceil(len(charts) / COLS)
W = PAD * 2 + CW * COLS + GAPX * (COLS - 1)
H = PAD * 2 + CH * nrows + GAPY * (nrows - 1)

img = Image.new('RGB', (W, H), 'white')
d = ImageDraw.Draw(img)
f_title = font(22, bold=True)
f_sub = font(15)
f_leg = font(14, bold=True)
f_tick = font(13)
f_x = font(14)
f_unit = font(13)

for idx, ch in enumerate(charts):
    r0, c0 = divmod(idx, COLS)
    ox = PAD + c0 * (CW + GAPX)
    oy = PAD + r0 * (CH + GAPY)
    # panel
    d.rounded_rectangle([ox, oy, ox + CW, oy + CH], radius=16, fill=PANEL,
                        outline=LINE)
    d.text((ox + 20, oy + 14), ch['title'], font=f_title, fill=INK)
    buffers = 'GPU memory' if ch['memory'] == 'gpu' else 'host memory'
    sub = (f"{ch['rw']}, {ch['iosize']} bytes, {ch['devcount']} devices, "
           f"buffers in {buffers}")
    d.text((ox + 20, oy + 48), sub, font=f_sub, fill=MUTED)
    # legend (top-right)
    lx = ox + CW - 186
    d.rectangle([lx, oy + 20, lx + 10, oy + 30], fill=UIO)
    d.text((lx + 14, oy + 17), 'UIO', font=f_leg, fill=INK)
    d.rectangle([lx + 70, oy + 20, lx + 80, oy + 30], fill=VFIO)
    d.text((lx + 84, oy + 17), 'VFIO', font=f_leg, fill=INK)
    # plot area
    PX, PY, PW, PH = 72, 92, CW - 90, CH - 92 - 36
    baseline = PY + PH
    values = [float(v) for v in ch['uio'] + ch['vfio']]
    maxv = max(values) * 1.08 if values else 1.0
    for i in range(5):
        val = maxv * i / 4
        y = baseline - PH * i / 4
        col = TCK if i == 0 else 'rgba_none'
        d.line([ox + PX, oy + y, ox + PX + PW, oy + y],
               fill=TCK if i > 0 else TCK, width=1)
        d.text((ox + PX - 8, oy + y - 8), compact(val), font=f_tick,
               fill=MUTED, anchor='rm')
    d.text((ox + 14, oy + PY - 4), ch['unit'], font=f_unit, fill=MUTED)
    n = max(len(ch['labels']), 1)
    gw = PW / n
    gbw = min(PW * 0.4, gw * 0.72)
    bw = gbw / 2
    for gi, lab in enumerate(ch['labels']):
        center = ox + PX + gi * gw + gw / 2
        left = center - gbw / 2
        for si, (val, col) in enumerate(
                [(ch['uio'][gi], UIO), (ch['vfio'][gi], VFIO)]):
            v = float(val)
            bh = v / maxv * PH
            x = left + si * bw + 2
            y = baseline - bh
            d.rounded_rectangle([x, oy + y, x + bw - 4, oy + baseline],
                                radius=5, fill=col)
        d.text((center, oy + baseline + 8), f'qd {lab}', font=f_x, fill=INK,
               anchor='ma')

img.save(OUT_PNG)
print(f'png: {OUT_PNG} {img.size}')


# ---- build XHTML ----
def esc(v):
    return str(v).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def num(v, nd=2):
    if v is None:
        return 'N/A'
    return ('%.' + str(nd) + 'f') % v


SUMMARY_HEAD = ['Runner', 'Buffers', 'RW', 'IO size', 'Devices', 'IO depth',
                'UIO IOPS', 'VFIO IOPS', 'IOPS delta %',
                'UIO MiB/s', 'VFIO MiB/s', 'MiB/s delta %',
                'UIO mean us', 'VFIO mean us', 'Latency delta %']

summary_lines = []
for r in rows:
    u, v = r['uio'], r['vfio']
    mean_u = num(u.get('lat_ns') and u['lat_ns'] / 1000.0)
    mean_v = num(v.get('lat_ns') and v['lat_ns'] / 1000.0)
    ld = r.get('lat_delta_pct')
    cells = [
        esc(r['runner']), esc(r.get('memory', 'host')), esc(r['rw']),
        esc(r['iosize']), esc(r.get('devcount', r['uio'].get('devcount', 1))),
        esc(r['iodepth']),
        num(u['iops']), num(v['iops']), num(r['iops_delta_pct']),
        num(u['mibs']), num(v['mibs']), num(r['mibs_delta_pct']),
        mean_u, mean_v, num(ld),
    ]
    summary_lines.append('<tr><td>' + '</td><td>'.join(cells) + '</td></tr>')

TH = ''.join(f'<th>{esc(h)}</th>' for h in SUMMARY_HEAD)
summary = ('<table><tbody>\n<tr>' + TH + '</tr>\n'
           + '\n'.join(summary_lines) + '\n</tbody></table>')

TAIL_HEAD = ['Runner', 'RW', 'IO size', 'IO depth',
             'P99.9 UIO us', 'P99.9 VFIO us',
             'P99.99 UIO us', 'P99.99 VFIO us',
             'P99.999 UIO us', 'P99.999 VFIO us']
tail_lines = []
for r in rows:
    if r['runner'] != 'fio':
        continue
    u, v = r['uio'], r['vfio']
    cells = [esc(r['runner']), esc(r['rw']), esc(r['iosize']),
             esc(r['iodepth'])]
    for k in ('p99_9', 'p99_99', 'p99_999'):
        cells.append(num(u['tail_lat_ns'][k] / 1000.0))
        cells.append(num(v['tail_lat_ns'][k] / 1000.0))
    tail_lines.append('<tr><td>' + '</td><td>'.join(cells) + '</td></tr>')
TH2 = ''.join(f'<th>{esc(h)}</th>' for h in TAIL_HEAD)
tail = ('<table><tbody>\n<tr>' + TH2 + '</tr>\n'
        + '\n'.join(tail_lines) + '\n</tbody></table>')

def delta_str(d):
    if d is None:
        return 'N/A'
    sign = '+' if d >= 0 else ''
    return sign + ('%.2f' % d) + '%'


cards = []
for ch in charts:
    buffers = 'GPU memory' if ch['memory'] == 'gpu' else 'host memory'
    sub = (f"{ch['rw']}, {ch['iosize']} bytes, {ch['devcount']} devices, "
           f"buffers in {buffers}")
    head = ['IO depth', 'Devices', f'UIO {ch["unit"]}', f'VFIO {ch["unit"]}',
            'Delta %']
    th = ''.join(f'<th>{esc(h)}</th>' for h in head)
    trs = []
    for r in ch['rows']:
        cells = [esc(r['iodepth']), esc(ch['devcount']), num(r['uio']),
                 num(r['vfio']), esc(delta_str(r['delta']))]
        trs.append('<tr><td>' + '</td><td>'.join(cells) + '</td></tr>')
    cards.append(
        '<ac:structured-macro ac:name="panel">\n'
        f'<ac:parameter ac:name="title">{esc(ch["title"])}</ac:parameter>\n'
        '<ac:rich-text-body>\n'
        f'<p>{esc(sub)}</p>\n'
        '<table><tbody>\n'
        f'<tr>{th}</tr>\n' + '\n'.join(trs) + '\n'
        '</tbody></table>\n'
        '</ac:rich-text-body>\n'
        '</ac:structured-macro>'
    )

frag = (
    '<p>This report compares an IOMMU-off run against an IOMMU-on run. The uPCIe '
    'path uses <code>uio_pci_generic</code> and <code>vfio-pci</code>; the kernel '
    'NVMe 4KB-page path uses raw <code>fio</code> through the <code>nvme</code> '
    'driver. Buffers sit in either host memory or GPU memory (hugepage).</p>\n'
    '<h2>Charts</h2>\n' + '\n'.join(cards) + '\n'
    '<h2>Summary</h2>\n' + summary + '\n'
)
OUT_XHTML.write_text(frag)
print(f'xhtml: {OUT_XHTML} {len(frag)} chars, {frag.count(chr(10))+1} lines')
