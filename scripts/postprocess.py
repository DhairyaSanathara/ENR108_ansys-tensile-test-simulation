"""Post-processes the ANSYS output in data/ into results/: comparison graphs, watermarked
contour plots and screenshots, and the Excel workbook.

Usage (from anywhere):  python scripts/postprocess.py
"""
import json, os, re, glob
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, LineChart, ScatterChart, Reference, Series
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter

REPO = Path(__file__).resolve().parents[1]
DATA = str(REPO / "data" / "raw")
RAW_CONTOURS = str(REPO / "data" / "contours_raw")
RAW_SHOTS = str(REPO / "data" / "screenshots_raw")
OUT = str(REPO / "results")
G_DIR, C_DIR, S_DIR = (os.path.join(OUT, d) for d in ("graphs", "contours", "screenshots"))
for d in (OUT, G_DIR, C_DIR, S_DIR):
    os.makedirs(d, exist_ok=True)

MARK = "\u00a9 ENR108 \u00b7 S3G6"
MARK_LONG = "\u00a9 ENR108 Section 3 \u00b7 Group S3G6 \u00b7 Ahmedabad University \u00b7 Lab 3"

# Material properties (ANSYS General Materials library)
MATS = [
    dict(name="Structural Steel", short="Steel", E=200, nu=0.30, rho=7850, yld=250, uts=460, strength=250, basis="Tensile yield"),
    dict(name="Aluminum Alloy", short="Aluminium", E=71, nu=0.33, rho=2770, yld=280, uts=310, strength=280, basis="Tensile yield"),
    dict(name="Polyethylene", short="Polyethylene", E=1.1, nu=0.42, rho=950, yld=25, uts=33, strength=25, basis="Tensile yield"),
    dict(name="Concrete", short="Concrete", E=30, nu=0.18, rho=2300, yld=None, uts=5, strength=5, basis="Tensile ultimate (brittle)"),
]
COLORS = {"Structural Steel": "#2a78d6", "Aluminum Alloy": "#eb6834", "Polyethylene": "#1baf7a", "Concrete": "#eda100"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
F_N, A_GAUGE = 5000.0, 39.0
SUM_L_OVER_A = 65.71 / 57 + 42.2 / 48 + 57 / 39  # grips + fillets + gauge, mm^-1

# ---------------------------------------------------------------- watermark
def font(size):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()

def watermark(src, dst):
    im = Image.open(src).convert("RGBA")
    W, H = im.size
    # faint diagonal tiled mark
    tile = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    f = font(max(18, W // 45))
    step_x, step_y = max(260, W // 4), max(140, H // 5)
    for yy in range(0, H * 2, step_y):
        for xx in range(-(yy // 2) % step_x, W * 2, step_x):
            d.text((xx, yy), "ENR108 S3G6", font=f, fill=(90, 90, 90, 26))
    tile = tile.rotate(28, resample=Image.BICUBIC)
    tile = tile.crop((W // 2, H // 2, W // 2 + W, H // 2 + H))
    im = Image.alpha_composite(im, tile)
    # footer strip with the copyright stamp (keeps chart content unobstructed)
    strip = max(30, H // 26)
    canvas = Image.new("RGBA", (W, H + strip), (255, 255, 255, 255))
    canvas.paste(im, (0, 0))
    im = canvas
    d = ImageDraw.Draw(im)
    d.rectangle((0, H, W, H + strip), fill=(31, 56, 100, 255))
    f2 = font(max(13, int(strip * 0.5)))
    box = d.textbbox((0, 0), MARK_LONG, font=f2)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text((W - tw - strip // 2, H + (strip - th) // 2 - box[1]), MARK_LONG, font=f2, fill=(255, 255, 255, 255))
    d.text((strip // 2, H + (strip - th) // 2 - box[1]), "S3G6", font=f2, fill=(255, 255, 255, 255))
    meta = PngInfo()
    meta.add_text("Copyright", MARK_LONG)
    meta.add_text("Author", "ENR108 Group S3G6")
    meta.add_text("Description", "ENR108 Lab 3 - Tensile test simulation (ANSYS). Property of Group S3G6.")
    im.convert("RGB").save(dst, pnginfo=meta)

# ---------------------------------------------------------------- data
res = [json.load(open(os.path.join(DATA, "result_%d.json" % i))) for i in range(1, 5)]
by = {r["material"]: r for r in res}
conv = json.load(open(os.path.join(DATA, "convergence.json")))

def read_path(tag, key):
    fn = os.path.join(DATA, "paths", "%s_%s.txt" % (tag, key))
    rows = []
    for line in open(fn, encoding="utf-8", errors="ignore"):
        parts = re.split(r"\t+", line.strip())
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            continue
        if len(nums) >= 2:
            rows.append((nums[0], nums[-1]))
    return rows

paths = {}
for i, m in enumerate(MATS):
    tag = "%d_%s" % (i + 1, m["name"].replace(" ", "_"))
    paths[m["name"]] = {k: read_path(tag, k) for k in ("stress", "strain", "deformation")}

# ---------------------------------------------------------------- graphs
plt.rcParams.update({"font.family": "Arial", "font.size": 11, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True})
graphs = []

def save(fig, name, caption):
    tmp = os.path.join(G_DIR, "_tmp.png")
    fig.savefig(tmp, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    dst = os.path.join(G_DIR, name)
    watermark(tmp, dst)
    os.remove(tmp)
    graphs.append((name, caption))

names = [m["name"] for m in MATS]
shorts = [m["short"] for m in MATS]
cols = [COLORS[n] for n in names]

def bar(values, ylabel, title, fname, caption, fmt, log=False, ref=None):
    fig, ax = plt.subplots(figsize=(8, 4.6))
    b = ax.bar(shorts, values, color=cols, width=0.55)
    if log:
        ax.set_yscale("log")
    for rect, v in zip(b, values):
        ax.annotate(fmt(v), (rect.get_x() + rect.get_width() / 2, rect.get_height()), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=10, color=INK)
    if ref:
        ax.axhline(ref[0], color=INK2, lw=1.2, ls="--")
        ax.text(3.45, ref[0], ref[1], ha="right", va="bottom", fontsize=9, color=INK2)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK)
    ax.grid(axis="x", visible=False)
    save(fig, fname, caption)

bar([by[n]["def_max"] for n in names], "Max total deformation (mm, log scale)",
    "Polyethylene stretches ~180\u00d7 more than steel under the same 5 kN load",
    "G01_max_deformation.png", "Maximum total deformation for each material (log scale).", lambda v: "%.3g mm" % v, log=True)
bar([by[n]["strain_max"] for n in names], "Max equivalent elastic strain (mm/mm, log scale)",
    "Strain follows 1/E: lowest for steel, highest for polyethylene",
    "G02_max_equivalent_strain.png", "Maximum equivalent elastic strain for each material (log scale).", lambda v: "%.3g" % v, log=True)
bar([by[n]["stress_max"] for n in names], "Max von Mises stress (MPa)",
    "Peak stress is ~131.8 MPa for every material",
    "G03_max_vonmises_stress.png", "Maximum equivalent (von Mises) stress: identical for all materials.", lambda v: "%.1f" % v,
    ref=(F_N / A_GAUGE, "Hand calc F/A = 128.2 MPa"))

# Stress vs strength
fig, ax = plt.subplots(figsize=(8, 4.6))
x = range(4)
ax.bar([i - 0.17 for i in x], [by[n]["stress_max"] for n in names], 0.32, color="#9a9994", label="FEA peak stress")
ax.bar([i + 0.17 for i in x], [m["strength"] for m in MATS], 0.32, color=cols, label="Material strength")
for i, m in enumerate(MATS):
    ax.annotate("%g" % m["strength"], (i + 0.17, m["strength"]), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=10)
    ax.annotate("%.0f" % by[m["name"]]["stress_max"], (i - 0.17, by[m["name"]]["stress_max"]), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=10, color=INK2)
ax.set_xticks(list(x)); ax.set_xticklabels(shorts)
ax.set_ylabel("Stress (MPa)")
ax.set_title("Only steel and aluminium are stronger than the applied stress", loc="left", fontsize=13, fontweight="bold")
ax.legend(frameon=False, loc="upper right")
ax.grid(axis="x", visible=False)
save(fig, "G04_stress_vs_strength.png", "FEA peak stress compared with material strength (yield; tensile ultimate for concrete). Coloured bars are strength.")

fos = [m["strength"] / by[m["name"]]["stress_max"] for m in MATS]
fig, ax = plt.subplots(figsize=(8, 4.6))
b = ax.bar(shorts, fos, color=cols, width=0.55)
ax.axhline(1, color="#e34948", lw=1.4, ls="--")
ax.text(3.45, 1.03, "FoS = 1 (failure)", ha="right", va="bottom", fontsize=9, color="#e34948")
for rect, v in zip(b, fos):
    ax.annotate("%.2f" % v, (rect.get_x() + rect.get_width() / 2, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=10)
ax.set_ylabel("Factor of safety (strength / peak stress)")
ax.set_title("Polyethylene and concrete fall below a factor of safety of 1", loc="left", fontsize=13, fontweight="bold")
ax.grid(axis="x", visible=False)
save(fig, "G05_factor_of_safety.png", "Factor of safety = strength / peak von Mises stress.")

# Distributions along the length
def dist(key, ylabel, title, fname, caption, log=False):
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    for n in names:
        p = paths[n][key]
        ax.plot([a - 82.5 for a, _ in p], [v for _, v in p], color=COLORS[n], lw=2, label=dict(zip(names, shorts))[n])
    if log:
        ax.set_yscale("log")
    for xv in (-28.5, 28.5):
        ax.axvline(xv, color=INK2, lw=0.8, ls=":")
    ax.text(0, ax.get_ylim()[1], "gauge section", ha="center", va="top", fontsize=9, color=INK2)
    ax.set_xlabel("Position along specimen, X (mm)  [force end = \u221282.5, fixed end = +82.5]")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax.legend(frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.38))
    save(fig, fname, caption)

dist("stress", "Von Mises stress (MPa)", "Stress distribution is the same for all materials: highest in the gauge",
     "G06_stress_distribution_along_length.png", "Von Mises stress along the specimen centre-line (all four materials overlap).")
dist("strain", "Equivalent strain (mm/mm, log scale)", "Strain distribution has the same shape, scaled by 1/E",
     "G07_strain_distribution_along_length.png", "Equivalent elastic strain along the centre-line (log scale).", log=True)
dist("deformation", "Total deformation (mm, log scale)", "Deformation grows from the fixed end to the loaded end",
     "G08_deformation_distribution_along_length.png", "Total deformation along the centre-line (log scale).", log=True)

# Deformation vs 1/E
fig, ax = plt.subplots(figsize=(8, 4.6))
inv = [1 / m["E"] for m in MATS]
dm = [by[m["name"]]["def_max"] for m in MATS]
k = sum(a * b for a, b in zip(inv, dm)) / sum(a * a for a in inv)
ax.plot([0, max(inv) * 1.05], [0, k * max(inv) * 1.05], color=INK2, lw=1.2, ls="--", label="Linear fit through origin")
for m, a, b in zip(MATS, inv, dm):
    ax.scatter([a], [b], s=70, color=COLORS[m["name"]], zorder=3, edgecolor="white", linewidth=1.5)
    ax.annotate(m["short"], (a, b), xytext=(8, -4), textcoords="offset points", fontsize=10)
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("1 / Young's modulus (1/GPa, log scale)")
ax.set_ylabel("Max deformation (mm, log scale)")
ax.set_title("Deformation is directly proportional to 1/E (Hooke's law)", loc="left", fontsize=13, fontweight="bold")
ax.legend(frameon=False)
save(fig, "G09_deformation_vs_inverse_E.png", "Maximum deformation against 1/E: all points lie on one line through the origin.")

# Hand vs FEA
fig, axs = plt.subplots(1, 2, figsize=(10, 4.4))
hand_def = [F_N / (m["E"] * 1000) * SUM_L_OVER_A for m in MATS]
for ax, hand, fea, lab in [(axs[0], [F_N / A_GAUGE / (m["E"] * 1000) for m in MATS], [by[m["name"]]["strain_max"] for m in MATS], "Max strain (mm/mm)"),
                           (axs[1], hand_def, dm, "Max deformation (mm)")]:
    ax.bar([i - 0.18 for i in x], hand, 0.34, color="#9a9994", label="Hand calculation")
    ax.bar([i + 0.18 for i in x], fea, 0.34, color=cols, label="ANSYS")
    ax.set_yscale("log"); ax.set_xticks(list(x)); ax.set_xticklabels(shorts, fontsize=9.5)
    ax.set_ylabel(lab + ", log scale"); ax.grid(axis="x", visible=False)
axs[0].legend(frameon=False, fontsize=9)
fig.suptitle("ANSYS agrees with hand calculations within ~3%", x=0.02, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout()
save(fig, "G10_hand_vs_ansys.png", "Hand calculation (grey) against ANSYS (coloured) for strain and deformation.")

# Mesh convergence
fig, axs = plt.subplots(1, 2, figsize=(10, 4.2))
nodes = [c["nodes"] for c in conv]
axs[0].plot(nodes, [c["stress_max"] for c in conv], "-o", color=COLORS["Structural Steel"], lw=2, ms=7)
axs[0].axhline(F_N / A_GAUGE, color=INK2, ls="--", lw=1); axs[0].text(nodes[-1], F_N / A_GAUGE, "F/A = 128.2", ha="right", va="bottom", fontsize=9, color=INK2)
axs[0].set_xlabel("Number of nodes"); axs[0].set_ylabel("Max von Mises stress (MPa)")
axs[1].plot(nodes, [c["def_max"] for c in conv], "-o", color=COLORS["Structural Steel"], lw=2, ms=7)
axs[1].set_xlabel("Number of nodes"); axs[1].set_ylabel("Max total deformation (mm)")
for c in conv:
    axs[1].annotate("%g mm" % c["element_size_mm"], (c["nodes"], c["def_max"]), xytext=(4, 6), textcoords="offset points", fontsize=8, color=INK2)
fig.suptitle("Mesh convergence (Steel): deformation converges; peak stress rises only at the fixed-corner singularity", x=0.02, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout()
save(fig, "G11_mesh_convergence.png", "Mesh convergence study for Structural Steel (element sizes labelled).")

# Elastic stress-strain lines (linear axes)
fig, ax = plt.subplots(figsize=(8.5, 4.8))
op = by["Structural Steel"]["stress_max"]
xmax = 0.5
for m in MATS:
    E = m["E"] * 1000
    eps_lim = m["strength"] / E * 100
    eps_op = op / E * 100
    ax.plot([0, min(eps_lim, xmax)], [0, min(m["strength"], E * xmax / 100)], color=COLORS[m["name"]], lw=2.2, label=m["short"])
    if eps_op > eps_lim:
        ax.plot([eps_lim, min(eps_op, xmax)], [m["strength"], min(op, E * xmax / 100)], color=COLORS[m["name"]], lw=1.4, ls=":")
    if eps_op <= xmax:
        ax.scatter([eps_op], [op], color=COLORS[m["name"]], s=60, zorder=3, edgecolor="white", linewidth=1.5)
ax.axhline(op, color=INK2, lw=0.8, ls="--")
ax.text(0.01, op + 4, "Operating stress ≈ %.1f MPa" % op, fontsize=9, color=INK2)
ax.annotate("Polyethylene reaches this stress only at\n%.1f%% strain (off chart) and yields at 25 MPa" % (op / 1100 * 100),
            (xmax, 1100 * xmax / 100), xytext=(0.27, 40), fontsize=9, color=INK2, arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))
ax.annotate("Concrete cracks at 5 MPa", (5 / 30000 * 100, 5), xytext=(0.05, 175), fontsize=9, color=INK2,
            arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))
ax.set_xlim(0, xmax); ax.set_ylim(0, 300)
ax.set_xlabel("Strain (%)"); ax.set_ylabel("Stress (MPa)")
ax.set_title("Hooke's law lines up to strength; dotted = beyond strength (fails)", loc="left", fontsize=13, fontweight="bold")
ax.legend(frameon=False, loc="upper right")
save(fig, "G12_elastic_stress_strain.png", "Linear-elastic stress-strain lines (σ = Eε) up to each material's strength; dots mark the 5 kN operating point.")

# ---------------------------------------------------------------- copy + watermark contours & screenshots
# raw images exist only after a fresh run_simulation.ps1; the committed results/ already hold watermarked copies
for f in sorted(glob.glob(os.path.join(RAW_CONTOURS, "*.png"))):
    watermark(f, os.path.join(C_DIR, os.path.basename(f)))
for f in sorted(glob.glob(os.path.join(RAW_SHOTS, "*.png"))):
    watermark(f, os.path.join(S_DIR, os.path.basename(f)))

# ---------------------------------------------------------------- Excel
wb = Workbook()
HDR = PatternFill("solid", fgColor="1F3864"); HF = Font(name="Arial", bold=True, color="FFFFFF")
BLUE = Font(name="Arial", color="0000FF"); BLK = Font(name="Arial"); BOLD = Font(name="Arial", bold=True)
YEL = PatternFill("solid", fgColor="FFFF00")
thin = Side(style="thin", color="BFBFBF"); BRD = Border(left=thin, right=thin, top=thin, bottom=thin)

def header(ws, row, labels, col=1):
    for j, h in enumerate(labels):
        c = ws.cell(row=row, column=col + j, value=h)
        c.fill, c.font, c.border = HDR, HF, BRD
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

def title(ws, text, sub=None):
    ws["A1"] = text; ws["A1"].font = Font(name="Arial", bold=True, size=14)
    if sub:
        ws["A2"] = sub; ws["A2"].font = Font(name="Arial", italic=True, color="595959")

def widths(ws, ws_w):
    for i, w in enumerate(ws_w, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

# README
ws = wb.active; ws.title = "README"
title(ws, "ENR108 Lab 3 - Simulation of Tensile Testing Using ANSYS Mechanical", MARK_LONG)
lines = [
    ("Sheets", ""),
    ("Inputs", "Load, geometry and material properties (blue = input values)"),
    ("Results_FEA", "ANSYS results for all 4 materials (Step 16 comparison data)"),
    ("Validation", "Hand calculations (formulas) vs ANSYS, % error and factor of safety"),
    ("Path_Distribution", "Stress, strain and deformation along the centre-line, per material"),
    ("Mesh_Convergence", "Structural Steel results for element sizes 6 mm to 1 mm"),
    ("Charts", "Native Excel charts of the comparison"),
    ("", ""),
    ("Legend", ""),
    ("Blue text", "Hard-coded input (from ANSYS library or lab handout)"),
    ("Black text", "Formula"),
    ("", ""),
    ("Software", "ANSYS Student 2026 R1 (Workbench + Mechanical), Static Structural"),
    ("Load case", "Fixed support at X = +82.5 mm end; Force X = -5000 N on X = -82.5 mm end"),
    ("Mesh (main runs)", "Default program-controlled mesh: %s nodes, %s elements" % (res[0]["nodes"], res[0]["elements"])),
    ("Date of simulation", "5 October 2026"),
]
for i, (a, b) in enumerate(lines, 4):
    ws.cell(row=i, column=1, value=a).font = BOLD
    ws.cell(row=i, column=2, value=b).font = BLK
widths(ws, [22, 90])

# Inputs
ws = wb.create_sheet("Inputs")
title(ws, "Inputs: load, geometry and material properties", "Source: lab handout; geometry measured from tensile.IGS in ANSYS; materials from ANSYS General Materials library")
inp = [("Applied force F (N)", F_N), ("Gauge width (mm)", 13), ("Thickness (mm)", 3), ("Grip width (mm)", 19),
       ("Overall length (mm)", 165), ("Gauge length (mm)", 57), ("Grip length, both ends (mm)", 65.71),
       ("Fillet length, both ends (mm)", 42.2), ("Fillet average width (mm)", 16)]
header(ws, 4, ["Parameter", "Value"])
for i, (a, v) in enumerate(inp, 5):
    ws.cell(row=i, column=1, value=a).font = BLK
    c = ws.cell(row=i, column=2, value=v); c.font = BLUE
ws["A14"] = "Gauge area A (mm\u00b2)"; ws["B14"] = "=B6*B7"
ws["A15"] = "Grip area (mm\u00b2)"; ws["B15"] = "=B8*B7"
ws["A16"] = "Fillet average area (mm\u00b2)"; ws["B16"] = "=B13*B7"
ws["A17"] = "\u03a3(L/A) for elongation (1/mm)"; ws["B17"] = "=B11/B15+B12/B16+B10/B14"
ws["A18"] = "Nominal gauge stress F/A (MPa)"; ws["B18"] = "=B5/B14"
for r in range(14, 19):
    ws.cell(row=r, column=1).font = BOLD
ws["B11"].comment = Comment("Estimated from CAD face areas: grip side face 98.57 mm2 / 3 mm thickness x 2 ends", "S3G6")
ws["B12"].comment = Comment("Estimated: 165 - 57 - 65.71 mm", "S3G6")
ws["B13"].comment = Comment("Average of grip (19 mm) and gauge (13 mm) widths - approximation", "S3G6")
header(ws, 21, ["Material", "Young's modulus E (GPa)", "Poisson's ratio", "Density (kg/m\u00b3)", "Tensile yield (MPa)", "Tensile ultimate (MPa)", "Strength used for FoS (MPa)", "Basis"])
for i, m in enumerate(MATS, 22):
    vals = [m["name"], m["E"], m["nu"], m["rho"], m["yld"] if m["yld"] else "n/a (brittle)", m["uts"], m["strength"], m["basis"]]
    for j, v in enumerate(vals, 1):
        c = ws.cell(row=i, column=j, value=v); c.font = BLUE if j in (2, 3, 4, 5, 6, 7) else BLK; c.border = BRD
widths(ws, [34, 16, 14, 16, 16, 18, 20, 26])

# Results_FEA
ws = wb.create_sheet("Results_FEA")
title(ws, "ANSYS results - Step 16 comparison (default mesh)", "Max/Min/Avg over the whole body. Units: mm, mm/mm, MPa, N")
cols_r = ["Material", "Max total deformation (mm)", "Min total deformation (mm)", "Avg total deformation (mm)",
          "Max equiv. strain (mm/mm)", "Min equiv. strain (mm/mm)", "Avg equiv. strain (mm/mm)",
          "Max von Mises stress (MPa)", "Min von Mises stress (MPa)", "Avg von Mises stress (MPa)",
          "Directional def. X min (mm)", "Max normal stress X (MPa)", "Reaction force X (N)", "Nodes", "Elements"]
keys = ["def_max", "def_min", "def_avg", "strain_max", "strain_min", "strain_avg", "stress_max", "stress_min", "stress_avg",
        "dirx_min", "sx_max", "reaction_x", "nodes", "elements"]
header(ws, 4, cols_r)
for i, r in enumerate(res, 5):
    ws.cell(row=i, column=1, value=r["material"]).font = BOLD
    for j, k in enumerate(keys, 2):
        c = ws.cell(row=i, column=j, value=r.get(k)); c.font = BLUE; c.border = BRD
        c.number_format = "0.000E+00" if "strain" in k else ("0.0000" if "def" in k or "dirx" in k else "0.00")
ws.row_dimensions[4].height = 45
ws["A10"] = "Ratio to steel"; ws["A10"].font = BOLD
header(ws, 11, ["Material", "Deformation / steel", "Strain / steel", "Stress / steel", "E_steel / E"])
for i in range(4):
    r = 12 + i; s = 5 + i
    ws.cell(row=r, column=1, value="=A%d" % s)
    ws.cell(row=r, column=2, value="=B%d/$B$5" % s).number_format = "0.00"
    ws.cell(row=r, column=3, value="=E%d/$E$5" % s).number_format = "0.00"
    ws.cell(row=r, column=4, value="=H%d/$H$5" % s).number_format = "0.000"
    ws.cell(row=r, column=5, value="=Inputs!$B$22/Inputs!B%d" % (22 + i)).number_format = "0.00"
ws["A17"] = "Deformation/steel matches E_steel/E: deformation is inversely proportional to Young's modulus."
ws["A17"].font = Font(name="Arial", italic=True)
widths(ws, [20] + [15] * 14)

# Validation
ws = wb.create_sheet("Validation")
title(ws, "Validation: hand calculation vs ANSYS", "\u03c3 = F/A;  \u03b5 = \u03c3/E;  \u0394L = (F/E)\u00b7\u03a3(L/A);  FoS = strength / peak stress")
header(ws, 4, ["Material", "E (MPa)", "Hand stress (MPa)", "ANSYS max stress (MPa)", "Stress error %", "Hand strain", "ANSYS max strain", "Strain error %",
               "Hand deformation (mm)", "ANSYS max deformation (mm)", "Deformation error %", "Strength (MPa)", "Factor of safety", "Safe? (FoS > 1)"])
for i in range(4):
    r = 5 + i; ir = 22 + i; rr = 5 + i
    f = ["=Inputs!A%d" % ir, "=Inputs!B%d*1000" % ir, "=Inputs!$B$18", "=Results_FEA!H%d" % rr, "=(D{0}-C{0})/C{0}".format(r),
         "=C{0}/B{0}".format(r), "=Results_FEA!E%d" % rr, "=(G{0}-F{0})/F{0}".format(r),
         "=Inputs!$B$5/B{0}*Inputs!$B$17".format(r), "=Results_FEA!B%d" % rr, "=(J{0}-I{0})/I{0}".format(r),
         "=Inputs!G%d" % ir, "=L{0}/D{0}".format(r), '=IF(M{0}>1,"Yes","No - fails")'.format(r)]
    fmts = [None, "0", "0.00", "0.00", "0.0%", "0.000E+00", "0.000E+00", "0.0%", "0.0000", "0.0000", "0.0%", "0", "0.00", None]
    for j, (v, nf) in enumerate(zip(f, fmts), 1):
        c = ws.cell(row=r, column=j, value=v); c.font = BLK; c.border = BRD
        if nf: c.number_format = nf
ws.row_dimensions[4].height = 45
ws["A10"] = "Errors of ~2-3% come from stress concentration at the fillet, the coarse default mesh and the fillet approximation in the hand calculation."
ws["A10"].font = Font(name="Arial", italic=True)
widths(ws, [20] + [14] * 13)

# Path distribution
ws = wb.create_sheet("Path_Distribution")
title(ws, "Distribution along the centre-line (X = -82.5 to +82.5 mm, Y = Z = 0)", "Exported from ANSYS path results, %d points per material" % len(paths[names[0]]["stress"]))
hdr = ["X position (mm)"]
for n in names:
    hdr += ["%s stress (MPa)" % dict(zip(names, shorts))[n], "%s strain" % dict(zip(names, shorts))[n], "%s deformation (mm)" % dict(zip(names, shorts))[n]]
header(ws, 4, hdr)
npts = min(len(paths[n][k]) for n in names for k in ("stress", "strain", "deformation"))
for p in range(npts):
    r = 5 + p
    ws.cell(row=r, column=1, value=round(paths[names[0]]["stress"][p][0] - 82.5, 4))
    for j, n in enumerate(names):
        for kk, key in enumerate(("stress", "strain", "deformation")):
            c = ws.cell(row=r, column=2 + 3 * j + kk, value=paths[n][key][p][1])
            c.number_format = "0.000E+00" if key == "strain" else "0.0000"
ws.row_dimensions[4].height = 45
ws.freeze_panes = "B5"
widths(ws, [14] + [14] * 12)
path_last = 4 + npts

# Mesh convergence
ws = wb.create_sheet("Mesh_Convergence")
title(ws, "Mesh convergence study - Structural Steel", "Body sizing applied to the whole specimen; default mesh shown for reference")
header(ws, 4, ["Element size (mm)", "Nodes", "Elements", "Max deformation (mm)", "Max equiv. strain", "Max von Mises stress (MPa)", "Change in stress vs previous"])
ws.cell(row=5, column=1, value="Default"); ws.cell(row=5, column=2, value=res[0]["nodes"]); ws.cell(row=5, column=3, value=res[0]["elements"])
ws.cell(row=5, column=4, value=res[0]["def_max"]); ws.cell(row=5, column=5, value=res[0]["strain_max"]); ws.cell(row=5, column=6, value=res[0]["stress_max"])
for i, c in enumerate(conv, 6):
    for j, k in enumerate(["element_size_mm", "nodes", "elements", "def_max", "strain_max", "stress_max"], 1):
        ws.cell(row=i, column=j, value=c[k]).font = BLUE
    ws.cell(row=i, column=7, value="=(F{0}-F{1})/F{1}".format(i, i - 1)).number_format = "0.00%"
for r in range(5, 6 + len(conv)):
    ws.cell(row=r, column=4).number_format = "0.00000"; ws.cell(row=r, column=5).number_format = "0.000E+00"; ws.cell(row=r, column=6).number_format = "0.00"
    for j in range(1, 8): ws.cell(row=r, column=j).border = BRD
ws.row_dimensions[4].height = 32
widths(ws, [16, 10, 10, 18, 16, 22, 22])
conv_last = 5 + len(conv)

# Charts sheet
ws = wb.create_sheet("Charts")
title(ws, "Charts", MARK_LONG)
R = wb["Results_FEA"]
def add_bar(col, ttl, ylab, anchor, log=False):
    ch = BarChart(); ch.type = "col"; ch.title = ttl; ch.y_axis.title = ylab; ch.legend = None
    ch.add_data(Reference(R, min_col=col, min_row=4, max_row=8), titles_from_data=True)
    ch.set_categories(Reference(R, min_col=1, min_row=5, max_row=8))
    if log: ch.y_axis.scaling.logBase = 10
    ch.height, ch.width = 7.5, 15
    ws.add_chart(ch, anchor)
add_bar(2, "Max total deformation (log scale)", "mm", "A4", log=True)
add_bar(5, "Max equivalent strain (log scale)", "mm/mm", "J4", log=True)
add_bar(8, "Max von Mises stress", "MPa", "A20")
V = wb["Validation"]
ch = BarChart(); ch.title = "Factor of safety"; ch.y_axis.title = "Strength / peak stress"; ch.legend = None
ch.add_data(Reference(V, min_col=13, min_row=4, max_row=8), titles_from_data=True)
ch.set_categories(Reference(V, min_col=1, min_row=5, max_row=8)); ch.height, ch.width = 7.5, 15
ws.add_chart(ch, "J20")
P = wb["Path_Distribution"]
ch = ScatterChart(); ch.title = "Von Mises stress along the specimen"; ch.x_axis.title = "X (mm)"; ch.y_axis.title = "MPa"; ch.style = 13
xref = Reference(P, min_col=1, min_row=5, max_row=path_last)
for j in range(4):
    s = Series(Reference(P, min_col=2 + 3 * j, min_row=4, max_row=path_last), xref, title_from_data=True)
    s.marker.symbol = "none"; s.smooth = False
    ch.series.append(s)
ch.height, ch.width = 7.5, 15
ws.add_chart(ch, "A36")
M = wb["Mesh_Convergence"]
ch = ScatterChart(); ch.title = "Mesh convergence - max stress vs nodes"; ch.x_axis.title = "Nodes"; ch.y_axis.title = "MPa"; ch.legend = None
s = Series(Reference(M, min_col=6, min_row=5, max_row=conv_last), Reference(M, min_col=2, min_row=5, max_row=conv_last), title="Max stress")
ch.series.append(s); ch.height, ch.width = 7.5, 15
ws.add_chart(ch, "J36")

for sh in wb.worksheets:
    for row in sh.iter_rows():
        for c in row:
            if c.font and c.font.name != "Arial":
                c.font = Font(name="Arial", bold=c.font.bold, italic=c.font.italic, color=c.font.color, size=c.font.size)
xlsx = os.path.join(OUT, "tensile_results.xlsx")
wb.save(xlsx)
print("built", xlsx, len(graphs), "graphs")
