# -*- coding: utf-8 -*-
"""
Calculator Pro 3.0
حاسبة علمية وهندسية متكاملة: حساب، معادلات، تفاضل وتكامل، رسم بياني تفاعلي، محول عملات ووحدات.

المتطلبات:  pip install customtkinter sympy numpy matplotlib
التشغيل:    python calculator_pro_v3.py
"""
from __future__ import annotations

import ast
import json
import math
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import warnings
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

import customtkinter as ctk
import numpy as np
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import sympy as sp

# ======================================================================
# معلومات البرنامج (عدّلها هنا فقط)
# ======================================================================
APP_NAME = "Calculator Pro"
APP_VERSION = "3.0"
DEVELOPER_NAME = "عبدالله مهيوب"
WHATSAPP_NUMBER = "+967777491747"
WHATSAPP_URL = "https://wa.me/967777491747"
COPYRIGHT_TEXT = "© 2026 جميع الحقوق محفوظة"
RATES_CREDIT_TEXT = "Rates By Exchange Rate API"
RATES_CREDIT_URL = "https://www.exchangerate-api.com"


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.getenv("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "CalculatorPro"


APP_DATA_DIR = app_data_dir()
RATES_FILE = APP_DATA_DIR / "exchange_rates.json"
LEGACY_RATES_FILE = Path.cwd() / "exchange_rates.json"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
ERROR_LOG = APP_DATA_DIR / "error.log"

TAB_CALC = "🧮 الحاسبة"
TAB_GRAPH = "📈 الرسم البياني"
TAB_CONV = "💱 المحولات"


# ======================================================================
# محرك الحساب (بدون واجهة — قابل للاختبار)
# ======================================================================
class MathError(ValueError):
    """خطأ حسابي برسالة عربية جاهزة للعرض."""


X = sp.Symbol("x")
MAX_BITS = 40000          # أقصى حجم لعدد صحيح ناتج
MAX_EXPR_LEN = 400
MAX_AST_NODES = 160

_TRANSLATE = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_TRANSLATE.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_TRANSLATE.update({
    ord("٫"): ".", ord("×"): "*", ord("÷"): "/", ord("−"): "-", ord("–"): "-",
    ord("٪"): "%", ord("π"): "pi", ord("،"): ",", ord("；"): ";",
})


def _trig(fn):
    return lambda args, deg: fn(args[0] * sp.pi / 180) if deg else fn(args[0])


def _itrig(fn):
    return lambda args, deg: fn(args[0]) * 180 / sp.pi if deg else fn(args[0])


def _fact(args, deg):
    a = args[0]
    if a.is_number:
        if not a.is_Integer:
            raise MathError("المضروب (!) يقبل أعدادًا صحيحة فقط")
        if a < 0 or a > 2000:
            raise MathError("المضروب يقبل عددًا بين 0 و 2000")
    return sp.factorial(a)


# اسم الدالة: (عدد المعاملات، التنفيذ)
FUNCTIONS = {
    "sin": (1, _trig(sp.sin)), "cos": (1, _trig(sp.cos)), "tan": (1, _trig(sp.tan)),
    "asin": (1, _itrig(sp.asin)), "acos": (1, _itrig(sp.acos)), "atan": (1, _itrig(sp.atan)),
    "sinh": (1, lambda a, d: sp.sinh(a[0])), "cosh": (1, lambda a, d: sp.cosh(a[0])),
    "tanh": (1, lambda a, d: sp.tanh(a[0])),
    "sqrt": (1, lambda a, d: sp.sqrt(a[0])),
    "cbrt": (1, lambda a, d: sp.real_root(a[0], 3)),
    "abs": (1, lambda a, d: sp.Abs(a[0])),
    "sign": (1, lambda a, d: sp.sign(a[0])),
    "exp": (1, lambda a, d: sp.exp(a[0])),
    "ln": (1, lambda a, d: sp.log(a[0])),
    "log": (1, lambda a, d: sp.log(a[0], 10)),
    "fact": (1, _fact),
    "floor": (1, lambda a, d: sp.floor(a[0])),
    "ceil": (1, lambda a, d: sp.ceiling(a[0])),
    "mod": (2, lambda a, d: sp.Mod(a[0], a[1])),
}
CONSTANTS = {"x": X, "pi": sp.pi, "e": sp.E}
_NAMES_BY_LEN = sorted(list(FUNCTIONS) + list(CONSTANTS), key=len, reverse=True)

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<id>[A-Za-z]+)"
    r"|(?P<op>[-+*/^(),%])"
    r"|(?P<bad>\S))"
)


def _split_identifier(word: str) -> list[str]:
    if word == "E":
        return ["e"]
    w, out, i = word.lower(), [], 0
    while i < len(w):
        for name in _NAMES_BY_LEN:
            if w.startswith(name, i):
                out.append(name)
                i += len(name)
                break
        else:
            raise MathError(f"الرمز غير معروف: {word}")
    return out


def _tokenize(source: str) -> list[tuple[str, str]]:
    src = source.translate(_TRANSLATE)
    tokens: list[tuple[str, str]] = []
    prev_kind, prev_end = None, -1
    for m in _TOKEN_RE.finditer(src):
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "num":
            if prev_kind == "num" and m.start("num") == prev_end:
                raise MathError("رقم غير صالح (فاصلتان عشريتان؟)")
            if re.fullmatch(r"\d+", text):
                text = str(int(text))
            tokens.append(("num", text))
        elif kind == "id":
            for name in _split_identifier(text):
                tokens.append(("func" if name in FUNCTIONS else "const", name))
        elif kind == "op":
            if text == "(":
                tokens.append(("lpar", "("))
            elif text == ")":
                tokens.append(("rpar", ")"))
            elif text == "%":   # نسبة مئوية = ÷100
                tokens.extend([("op", "*"), ("lpar", "("), ("num", "1"), ("op", "/"),
                               ("num", "100"), ("rpar", ")")])
            elif text == "^":
                tokens.append(("op", "**"))
            else:
                tokens.append(("op", text))
        else:
            raise MathError(f"رمز غير مدعوم: {text}")
        prev_kind, prev_end = kind, m.end(kind)
    # الضرب الضمني: 2x ، 2(3) ، )( ، 2sin(x) ...
    out: list[tuple[str, str]] = []
    for tok in tokens:
        if out and out[-1][0] in ("num", "const", "rpar") and tok[0] in ("num", "const", "func", "lpar"):
            out.append(("op", "*"))
        out.append(tok)
    return out


def _check_size(v):
    if isinstance(v, sp.Integer) and abs(int(v)).bit_length() > MAX_BITS:
        raise MathError("العدد الناتج كبير جدًا")
    return v


def parse_expression(source: str, angle_mode: str = "Radians") -> sp.Expr:
    """تحليل آمن لتعبير رياضي (لا يُنفَّذ أي كود بايثون)."""
    if not isinstance(source, str) or not source.strip():
        raise MathError("التعبير فارغ")
    if len(source) > MAX_EXPR_LEN:
        raise MathError("التعبير طويل جدًا")
    deg = angle_mode == "Degrees"
    text = "".join(t for _, t in _tokenize(source))
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise MathError("صيغة التعبير غير صحيحة — تحقق من الأقواس والعمليات") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise MathError("التعبير معقد جدًا")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            val = node.value
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise MathError("قيمة غير مدعومة")
            if isinstance(val, int):
                return sp.Integer(val)
            if not math.isfinite(val):
                raise MathError("الأعداد اللانهائية غير مسموحة")
            return sp.Rational(repr(val))
        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            if node.id in FUNCTIONS:
                raise MathError(f"الدالة {node.id} تحتاج أقواسًا، مثال: {node.id}(…)")
            raise MathError(f"الرمز غير معروف: {node.id}")
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            op = type(node.op)
            if op is ast.Add:
                return left + right
            if op is ast.Sub:
                return left - right
            if op is ast.Mult:
                return _check_size(left * right)
            if op is ast.Div:
                return left / right
            if op is ast.Pow:
                if right.is_Integer and abs(int(right)) > 10000 and left not in (0, 1, -1):
                    raise MathError("الأس كبير جدًا")
                return _check_size(left ** right)
            raise MathError("عملية غير مدعومة")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = visit(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            nargs, impl = FUNCTIONS[node.func.id]
            if node.keywords or len(node.args) != nargs:
                raise MathError(f"الدالة {node.func.id} تقبل {nargs} معاملًا")
            return impl([visit(a) for a in node.args], deg)
        raise MathError("صيغة رياضية غير مدعومة")

    try:
        return sp.sympify(visit(tree))
    except RecursionError:
        raise MathError("التعبير معقد جدًا") from None


def sym_str(expr) -> str:
    """نص رمزي قابل لإعادة الإدخال في الحاسبة قدر الإمكان."""
    s = str(expr).replace("**", "^")
    s = re.sub(r"\blog\(", "ln(", s)
    s = s.replace("Abs(", "abs(")
    s = re.sub(r"\bE\b", "e", s)
    s = re.sub(r"\bI\b", "i", s)
    return s


def _fmt_real(v) -> str:
    try:
        f = float(v)
    except (OverflowError, ValueError, TypeError):
        f = float("inf")
    if not math.isfinite(f):
        return str(sp.N(v, 10))
    if f == 0:
        return "0"
    s = format(f, ".12g")
    if "e" in s:
        mant, exp = s.split("e")
        s = f"{mant}e{int(exp)}"
    return s


def format_value(expr) -> str:
    expr = sp.sympify(expr)
    if expr.has(sp.zoo, sp.nan, sp.oo, sp.S.NegativeInfinity):
        raise MathError("قسمة على صفر أو نتيجة غير معرّفة")
    if expr.free_symbols:
        return sym_str(expr)
    if expr.is_Integer:
        if abs(int(expr)).bit_length() > 3000:      # تجنّب حد تحويل الأعداد الضخمة إلى نص
            return str(sp.N(expr, 12)).replace("e+", "e")
        s = str(int(expr))
        digits = len(s.lstrip("-"))
        if digits <= 30:
            return s
        return f"{float(sp.N(expr, 15)):.11e}".replace("e+", "e") if digits < 300 else str(sp.N(expr, 12)).replace("e+", "e")
    try:
        val = expr.evalf(30)
        re_part, im_part = val.as_real_imag()
    except Exception:
        return sym_str(expr)
    if abs(im_part) <= 1e-18 * max(1, abs(re_part)):
        return _fmt_real(re_part)
    sign = "-" if im_part < 0 else "+"
    return f"{_fmt_real(re_part)} {sign} {_fmt_real(abs(im_part))}i"


def format_number(value) -> str:
    """تنسيق رقم عادي (للذاكرة وغيرها)."""
    try:
        return format_value(sp.Float(value) if isinstance(value, float) else value)
    except Exception:
        return str(value)


def numeric_roots(expr, lo=-50.0, hi=50.0, n=20001, limit=8) -> list[float]:
    """بحث عددي عن الجذور (احتياطي عند فشل الحل الرمزي)."""
    try:
        f = sp.lambdify(X, expr, modules=["numpy"])
        xs = np.linspace(lo, hi, n)
        with np.errstate(all="ignore"):
            ys = np.broadcast_to(np.asarray(f(xs), dtype=float), xs.shape)
        roots: list[float] = []
        ok = np.isfinite(ys[:-1]) & np.isfinite(ys[1:])
        idx = np.where(ok & (np.sign(ys[:-1]) * np.sign(ys[1:]) <= 0))[0]
        for i in idx:
            a, b = float(xs[i]), float(xs[i + 1])
            fa = float(ys[i])
            for _ in range(80):
                m = (a + b) / 2
                fm = float(f(m))
                if fa * fm <= 0:
                    b = m
                else:
                    a, fa = m, fm
            r = (a + b) / 2
            with np.errstate(all="ignore"):
                residual = abs(float(f(r)))
            if residual < 1e-6 and all(abs(r - q) > 1e-6 for q in roots):
                roots.append(r)
            if len(roots) >= limit:
                break
        return roots
    except Exception:
        return []


def solve_equation(lhs, rhs) -> str:
    if X not in lhs.free_symbols.union(rhs.free_symbols):
        if lhs.has(sp.zoo, sp.nan) or rhs.has(sp.zoo, sp.nan):
            raise MathError("قسمة على صفر أو نتيجة غير معرّفة")
        same = sp.simplify(lhs - rhs) == 0 or bool(sp.N(lhs - rhs, 20).equals(0))
        return "العبارة صحيحة ✓" if same else "العبارة غير صحيحة ✗"
    eq = sp.Eq(lhs, rhs)
    diff_expr = lhs - rhs
    try:
        sols = sp.solve(eq, X)
        if not sols and sp.simplify(diff_expr) == 0:
            return "المعادلة متطابقة: كل قيمة لـ x تحققها"
    except (NotImplementedError, ValueError, TypeError):
        sols = None
    parts: list[str] = []
    if sols:
        for s in sols[:8]:
            exact = sym_str(s)
            if s.is_real is False:          # جذور مركبة: نعرضها رمزيًا فقط
                parts.append(f"x = {exact}")
                continue
            try:
                approx = format_value(sp.N(s, 20))
            except Exception:
                approx = exact
            if s.is_Rational or approx == exact:
                parts.append(f"x = {exact}")
            else:
                parts.append(f"x = {exact} ≈ {approx}")
        if len(sols) > 8:
            parts.append("…")
    else:
        roots = numeric_roots(diff_expr)
        if roots:
            parts = [f"x ≈ {_fmt_real(r)}" for r in roots]
            parts.append("(حل تقريبي ضمن [-50, 50])")
        else:
            return "لا يوجد حل"
    return "  ؛  ".join(parts)


def evaluate_text(source: str, angle_mode: str = "Radians") -> tuple[str, bool]:
    """يعيد (نص النتيجة، هل النتيجة تعبير قابل للاستكمال)."""
    src = source.strip()
    if not src:
        return "", False
    translated = src.translate(_TRANSLATE)
    if translated.count("=") > 1:
        raise MathError("يُسمح بعلامة = واحدة فقط")
    if "=" in translated:
        left, right = translated.split("=", 1)
        if not left.strip() or not right.strip():
            raise MathError("المعادلة ناقصة")
        return solve_equation(parse_expression(left, angle_mode), parse_expression(right, angle_mode)), False
    expr = parse_expression(src, angle_mode)
    return format_value(expr), True


def derivative_text(source: str, angle_mode: str = "Radians") -> str:
    if "=" in source:
        raise MathError("أدخل دالة بدون علامة =")
    expr = parse_expression(source, angle_mode)
    return format_value(sp.diff(expr, X))


def integral_text(source: str, angle_mode: str = "Radians") -> str:
    if "=" in source:
        raise MathError("أدخل دالة بدون علامة =")
    expr = parse_expression(source, angle_mode)
    res = sp.integrate(expr, X)
    if res.has(sp.Integral):
        raise MathError("تعذر إيجاد التكامل رمزيًا لهذه الدالة")
    return format_value(res) + " + C"


def parse_amount(text: str) -> float | None:
    """قراءة مبلغ/قيمة رقمية (تقبل عمليات حسابية وأرقامًا عربية)."""
    if not text or not text.strip():
        return None
    try:
        expr = parse_expression(text)
        if expr.free_symbols:
            return None
        val = complex(expr.evalf())
        if abs(val.imag) > 1e-12 or not math.isfinite(val.real):
            return None
        return float(val.real)
    except Exception:
        return None


def make_curve(expr):
    """يحوّل تعبيرًا رمزيًا إلى دالة عددية تتحمل القيم غير المعرفة."""
    f_np = sp.lambdify(X, expr, modules=["numpy"])
    state = {"mp": None}

    def pointwise(xs):
        if state["mp"] is None:
            state["mp"] = sp.lambdify(X, expr, modules=["mpmath"])
        out = np.full(xs.shape, np.nan)
        for i, xv in enumerate(xs):
            try:
                v = complex(state["mp"](float(xv)))
                if abs(v.imag) < 1e-9:
                    out[i] = v.real
            except Exception:
                pass
        return out

    def call(xs):
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                y = np.asarray(f_np(xs))
                if y.shape != xs.shape:
                    y = np.broadcast_to(y, xs.shape) if y.size == 1 else pointwise(xs)
                if np.iscomplexobj(y):
                    y = np.where(np.abs(y.imag) <= 1e-9 * np.maximum(1, np.abs(y.real)), y.real, np.nan)
                y = np.array(y, dtype=float)
            except Exception:
                y = pointwise(xs)
            y[~np.isfinite(y)] = np.nan
            y[np.abs(y) > 1e12] = np.nan
            return y

    return call


def break_discontinuities(ys: np.ndarray) -> np.ndarray:
    """يقطع الخط عند القفزات الحادة (مثل tan(x) و 1/x)."""
    finite = ys[np.isfinite(ys)]
    if finite.size < 3:
        return ys
    lo, hi = np.percentile(finite, [2, 98])
    span = max(hi - lo, 1e-9)
    ys = ys.copy()
    with np.errstate(all="ignore"):
        jumps = np.abs(np.diff(ys)) > 8 * span
    ys[1:][jumps] = np.nan
    return ys


# ======================================================================
# العملات والوحدات
# ======================================================================
# كود العملة: (الاسم، عدد الوحدات لكل 1 دولار — قيمة افتراضية تقريبية حتى أول تحديث)
CURRENCIES = {
    "USD": ("دولار أمريكي", 1.0),
    "SAR": ("ريال سعودي", 3.75),
    "YER": ("ريال يمني", 536.0),
    "QAR": ("ريال قطري", 3.64),
    "AED": ("درهم إماراتي", 3.6725),
    "KWD": ("دينار كويتي", 0.307),
    "OMR": ("ريال عُماني", 0.3845),
    "BHD": ("دينار بحريني", 0.376),
    "JOD": ("دينار أردني", 0.709),
    "EGP": ("جنيه مصري", 48.0),
    "EUR": ("يورو", 0.9259),
    "GBP": ("جنيه إسترليني", 0.7874),
    "CNY": ("يوان صيني", 7.2),
    "TRY": ("ليرة تركية", 41.0),
    "INR": ("روبية هندية", 88.0),
}
DEFAULT_SOURCE_LABEL = "أسعار افتراضية تقريبية"


def currency_label(code: str) -> str:
    return code      # الرمز فقط في القوائم حتى لا يُقتطع النص عند التصغير؛ الاسم يظهر تحت النتيجة


def _parse_er_api(data, codes):
    if not isinstance(data, dict) or data.get("result") != "success" or not isinstance(data.get("rates"), dict):
        raise ValueError("استجابة غير صالحة")
    out = {c: float(data["rates"][c]) for c in codes if c in data["rates"]}
    stamp = data.get("time_last_update_unix")
    date = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d") if isinstance(stamp, (int, float)) else None
    return out, date


def _parse_frankfurter(data, codes):
    if isinstance(data, dict) and isinstance(data.get("rates"), dict):      # شكل v1
        out = {c: float(v) for c, v in data["rates"].items() if c in codes}
        return out, data.get("date")
    if not isinstance(data, list):
        raise ValueError("استجابة غير صالحة")
    out, dates = {}, []
    for rec in data:
        code, rate = rec.get("quote"), rec.get("rate")
        if code in codes and isinstance(rate, (int, float)):
            out[code] = float(rate)
            if isinstance(rec.get("date"), str):
                dates.append(rec["date"])
    return out, (min(dates) if dates else None)


RATE_SOURCES = [
    ("ExchangeRate-API", lambda codes: "https://open.er-api.com/v6/latest/USD", _parse_er_api),
    ("Frankfurter", lambda codes: "https://api.frankfurter.dev/v2/rates?" +
        urllib.parse.urlencode({"base": "USD", "quotes": ",".join(codes)}), _parse_frankfurter),
]


def fetch_rates_online(codes):
    """يجلب الأسعار من المصادر بالترتيب. يعيد (الأسعار، التاريخ، المصادر، الناقص)."""
    wanted = [c for c in codes if c != "USD"]
    results, errors, sources, dates = {}, [], [], []
    for name, url_fn, parser in RATE_SOURCES:
        need = [c for c in wanted if c not in results]
        if not need:
            break
        try:
            req = urllib.request.Request(url_fn(need), headers={"User-Agent": f"CalculatorPro/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            got, date = parser(data, need)
            good = {c: v for c, v in got.items() if math.isfinite(v) and v > 0}
            if good:
                results.update(good)
                sources.append(name)
                if date:
                    dates.append(date)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    if not results:
        raise RuntimeError("تعذر الاتصال بمصدر الأسعار. تحقق من الإنترنت.\n" + "\n".join(errors[:2]))
    results["USD"] = 1.0
    missing = [c for c in wanted if c not in results]
    return results, (min(dates) if dates else datetime.now().strftime("%Y-%m-%d")), sources, missing


def format_money(v: float) -> str:
    if v == 0:
        return "0"
    if abs(v) < 0.0001 or abs(v) >= 1e15:
        return _fmt_real(v)
    s = f"{v:,.4f}".rstrip("0").rstrip(".")
    return s


# فئة: {الرمز: (المعامل إلى الوحدة الأساسية، الاسم)}
UNIT_CATEGORIES = {
    "الطول": {"km": (1000.0, "كيلومتر"), "m": (1.0, "متر"), "cm": (0.01, "سنتيمتر"), "mm": (0.001, "مليمتر"),
              "inch": (0.0254, "إنش"), "ft": (0.3048, "قدم"), "yd": (0.9144, "ياردة"), "mi": (1609.344, "ميل")},
    "الوزن": {"ton": (1000.0, "طن"), "kg": (1.0, "كيلوجرام"), "g": (0.001, "جرام"), "mg": (1e-6, "مليجرام"),
              "lb": (0.45359237, "رطل"), "oz": (0.028349523125, "أونصة")},
    "المساحة": {"km²": (1e6, "كيلومتر²"), "ha": (1e4, "هكتار"), "m²": (1.0, "متر²"), "cm²": (1e-4, "سنتيمتر²"),
                "ft²": (0.09290304, "قدم²"), "in²": (0.00064516, "إنش²"), "acre": (4046.8564224, "فدان إنجليزي")},
    "الحجم": {"m³": (1000.0, "متر³"), "L": (1.0, "لتر"), "mL": (0.001, "مليلتر"),
              "gal": (3.785411784, "جالون أمريكي"), "fl oz": (0.0295735295625, "أونصة سائلة")},
    "السرعة": {"m/s": (1.0, "متر/ثانية"), "km/h": (1 / 3.6, "كم/ساعة"), "mph": (0.44704, "ميل/ساعة"),
               "knot": (0.514444444, "عقدة")},
    "الحرارة": {"C": (0, "سيلسيوس"), "F": (0, "فهرنهايت"), "K": (0, "كلفن")},
}


def convert_unit(value: float, category: str, src: str, dst: str) -> float:
    if category == "الحرارة":
        if src == "C":
            c = value
        elif src == "F":
            c = (value - 32) * 5.0 / 9.0
        else:
            c = value - 273.15
        if c < -273.15 - 1e-9:
            raise MathError("درجة الحرارة أقل من الصفر المطلق")
        return c if dst == "C" else (c * 9.0 / 5.0 + 32 if dst == "F" else c + 273.15)
    units = UNIT_CATEGORIES[category]
    return value * units[src][0] / units[dst][0]


# ======================================================================
# الإعدادات
# ======================================================================
def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_json(path: Path, data) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ======================================================================
# نصوص الشرح (تظهر بالزر الأيمن)
# ======================================================================
HELP = {
    ".": ("الفاصلة العشرية", "تُدخل علامة الكسر العشري. مثال: 3.5"),
    "00": ("صفران", "يُدخل صفرين معًا لتسريع كتابة الأعداد الكبيرة."),
    "+": ("جمع", "يجمع رقمين. مثال: 2 + 3 = 5"),
    "−": ("طرح", "يطرح الرقم الثاني من الأول. مثال: 9 − 4 = 5"),
    "×": ("ضرب", "يضرب رقمين. مثال: 6 × 7 = 42"),
    "÷": ("قسمة", "يقسم الرقم الأول على الثاني. مثال: 20 ÷ 4 = 5"),
    "%": ("النسبة المئوية", "تقسم الرقم الذي قبلها على 100. مثال: 50% = 0.5 ، و 200 × 10% = 20"),
    "(": ("فتح قوس", "يبدأ مجموعة حسابية تُحسب أولًا. مثال: (2 + 3) × 4 = 20"),
    ")": ("إغلاق قوس", "ينهي المجموعة الحسابية التي بدأها القوس المفتوح."),
    "^": ("الأس", "يرفع الرقم إلى القوة التي تكتبها بعده. مثال: 2^3 = 8"),
    "x²": ("تربيع", "يرفع كامل التعبير الظاهر إلى القوة 2. مثال: (3+1) ثم x² = 16"),
    "1/x": ("المقلوب", "يحوّل التعبير الظاهر إلى مقلوبه. مثال: 4 ثم 1/x = 0.25"),
    "√": ("الجذر التربيعي", "يكتب √( ؛ أدخل الرقم ثم أغلق القوس. مثال: √(16) = 4"),
    "sin": ("جيب الزاوية", "أدخل الزاوية ثم أغلق القوس. وحدة الزاوية (راديان/درجات) من المفتاح العلوي. مثال بالدرجات: sin(30) = 0.5"),
    "cos": ("جيب التمام", "أدخل الزاوية ثم أغلق القوس. مثال بالدرجات: cos(60) = 0.5"),
    "tan": ("ظل الزاوية", "أدخل الزاوية ثم أغلق القوس. مثال بالدرجات: tan(45) = 1"),
    "asin": ("معكوس الجيب", "يعطي الزاوية التي جيبها يساوي القيمة. مثال بالدرجات: asin(0.5) = 30"),
    "acos": ("معكوس جيب التمام", "يعطي الزاوية التي جيب تمامها يساوي القيمة. مثال بالدرجات: acos(0.5) = 60"),
    "atan": ("معكوس الظل", "يعطي الزاوية التي ظلها يساوي القيمة. مثال بالدرجات: atan(1) = 45"),
    "ln": ("اللوغاريتم الطبيعي", "لوغاريتم أساس e. مثال: ln(e) = 1"),
    "log": ("اللوغاريتم العشري", "لوغاريتم أساس 10. مثال: log(1000) = 3"),
    "π": ("ثابت باي", "يُدخل π ≈ 3.14159265359"),
    "e": ("ثابت أويلر", "يُدخل e ≈ 2.71828182846"),
    "n!": ("المضروب", "يحسب مضروب عدد صحيح. مثال: fact(5) = 120"),
    "x": ("المتغير x", "يُدخل المتغير x لاستخدامه في المعادلات والتفاضل والتكامل والرسم."),
    "x = ؟": ("معادلة", "يُدخل علامة = لكتابة معادلة مثل x^2 = 4 ثم اضغط زر = لحلها."),
    "d/dx": ("المشتقة", "يحسب مشتقة التعبير الظاهر بالنسبة إلى x. مثال: x^3 ثم d/dx = 3*x^2"),
    "∫dx": ("التكامل", "يحسب التكامل غير المحدد للتعبير الظاهر بالنسبة إلى x. مثال: 2x ثم ∫dx = x^2 + C"),
    "MC": ("مسح الذاكرة", "يصفّر القيمة المحفوظة في الذاكرة."),
    "MR": ("استرجاع الذاكرة", "يُدخل القيمة المحفوظة في الذاكرة إلى الشاشة."),
    "M+": ("إضافة للذاكرة", "يجمع القيمة الظاهرة إلى الذاكرة."),
    "M−": ("طرح من الذاكرة", "يطرح القيمة الظاهرة من الذاكرة."),
    "⌫": ("حذف", "يحذف آخر رمز قبل المؤشر. (اختصار: Backspace)"),
    "C": ("مسح الشاشة", "يمسح التعبير الحالي بالكامل. (اختصار: Esc)"),
    "=": ("احسب / حل", "يحسب التعبير، أو يحل المعادلة إذا كانت تحتوي علامة =. (اختصار: Enter)"),
    "plot": ("ارسم الدالة", "ينقل التعبير الظاهر إلى تبويب الرسم ويرسمه بدلالة x."),
}
for _d in "0123456789":
    HELP[_d] = (f"الرقم {_d}", f"يُدخل الرقم {_d} في الشاشة.")


# ======================================================================
# التطبيق
# ======================================================================
FONT_SPECS = {          # الاسم: (الحجم الأساسي، الوزن)
    "btn": (15, "bold"), "small_btn": (13, "bold"), "body": (15, "normal"), "bold": (15, "bold"),
    "small": (13, "normal"), "section": (19, "bold"), "display": (36, "bold"), "result": (28, "bold"),
    "tab": (15, "bold"),
}
ERR_COLOR = ("#c0392b", "#ff7b72")
OK_COLOR = ("#1e8449", "#7ee2a8")
MUTED = ("gray35", "gray65")
KEY_STYLES = {          # الدور: (الخلفية، التمرير، لون النص) — (فاتح، داكن)
    "num": (("#f3f4f6", "#33373d"), ("#e5e7eb", "#41464e"), ("#111827", "#f3f4f6")),
    "op": (("#dbe5f6", "#2b3a55"), ("#c9d8f0", "#37496b"), ("#1b3a6b", "#d5e4ff")),
    "func": (("#e6e0f4", "#3b3350"), ("#d8d0ec", "#483f62"), ("#3b2a6b", "#e8defe")),
    "calc": (("#d6eee7", "#1f4a42"), ("#c3e6dc", "#295c52"), ("#0e4a3f", "#c4f5e8")),
    "mem": (("#e5e7eb", "#2a2e35"), ("#d5d8de", "#383d46"), ("#374151", "#b3bbc7")),
    "clear": (("#f8d7d3", "#5a2823"), ("#f1c3bd", "#6e322c"), ("#8a1c12", "#ffd0ca")),
    "back": (("#fbe3cf", "#5a3a1e"), ("#f6d3b6", "#6d4824"), ("#8a4a12", "#ffdcbc")),
    "plot": (("#d6e6fb", "#1f4272"), ("#c3d9f6", "#295286"), ("#0f3d78", "#cfe3ff")),
    "equals": (("#2f9e63", "#2f9e63"), ("#27875a", "#27875a"), ("#ffffff", "#ffffff")),
    "tool": (("#e5e7eb", "#2e3238"), ("#d5d8de", "#3b4047"), ("#1f2937", "#e5e7eb")),
}
ALLOWED_TYPING = set("0123456789+-*/().^%x=,")
PLOT_COLORS_DARK = ["#4aa3ff", "#ff8a65", "#4cd39a", "#c792ea", "#ffd166", "#ef5b9c"]
PLOT_COLORS_LIGHT = ["#1565c0", "#d84315", "#1f8a5b", "#7b3fb5", "#b8860b", "#c2185b"]
FONT_PREFERENCE = ("Tahoma", "Segoe UI", "Arial", "Noto Sans Arabic", "DejaVu Sans", "Helvetica")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class CalculatorProApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_json(SETTINGS_FILE) or {}
        theme = self.settings.get("theme", "dark")
        ctk.set_appearance_mode(theme if theme in ("dark", "light") else "dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.minsize(780, 560)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # الحالة
        self.angle_mode = "Degrees" if self.settings.get("angle") == "Degrees" else "Radians"
        self.memory = 0.0
        self.result_shown = False
        self.result_chainable = False
        self.history_items: list[tuple[str, str]] = []
        self.help_popup = None
        self.help_hide_job = None
        self._resize_job = None
        self._preview_job = None
        self._status_job = None
        self._font_scale = 1.0
        self._closing = False
        self._last_error_dialog = 0.0
        self._return_handlers = {}
        self._jobs = {}
        self._job_id = 0
        self._job_deadline = 0.0
        self._job_queue: queue.Queue = queue.Queue()
        self.rate_queue: queue.Queue = queue.Queue()
        self.rate_refreshing = False
        self.plot_funcs: list[tuple[str, callable]] = []
        self.view = [-10.0, 10.0, -6.0, 6.0]
        self.auto_y = True
        self._pan = None
        self._plot_scale = 1.0
        self._plot_ready = False
        self._plot_job = None

        self.load_rates()
        self._init_fonts()
        self._set_initial_geometry()
        self.setup_ui()
        self.bind_shortcuts()
        self.bind("<Configure>", self.on_window_configure, add="+")
        self.bind_all("<Button-1>", self.hide_help, add="+")
        self.bind_all("<Key>", self.hide_help, add="+")
        self.after(250, self.display.focus_set)
        self.after(1200, self.auto_refresh_rates_if_stale)
        self.after(60, self.apply_layout_scale)

    # ------------------------------------------------------------------
    # أساسيات
    # ------------------------------------------------------------------
    def _dpi_scale(self) -> float:
        try:
            return max(0.75, self.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            return 1.0

    def _init_fonts(self):
        try:
            available = set(tkfont.families(self))
        except tk.TclError:
            available = set()
        self.font_family = next((f for f in FONT_PREFERENCE if f in available), None)
        self.fonts = {k: ctk.CTkFont(family=self.font_family, size=s, weight=w) for k, (s, w) in FONT_SPECS.items()}

    def _set_initial_geometry(self):
        try:
            scaling = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            scaling = self._dpi_scale()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = int(clamp(sw / scaling * 0.92, 780, 1120))
        h = int(clamp(sh / scaling * 0.88, 560, 740))
        self.geometry(f"{w}x{h}")

    def report_callback_exception(self, exc, val, tb):
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            with ERROR_LOG.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{''.join(traceback.format_exception(exc, val, tb))}\n")
        except OSError:
            pass
        if time.monotonic() - self._last_error_dialog > 5 and not self._closing:
            self._last_error_dialog = time.monotonic()
            messagebox.showerror("خطأ غير متوقع",
                                 f"حدث خطأ غير متوقع لكن البرنامج ما زال يعمل.\n{exc.__name__}: {str(val)[:150]}\n"
                                 f"تم تسجيل التفاصيل في:\n{ERROR_LOG}", parent=self)

    def on_close(self):
        self._closing = True
        self.settings.update({"theme": ctk.get_appearance_mode().lower(), "angle": self.angle_mode})
        save_json(SETTINGS_FILE, self.settings)
        for job in (self._resize_job, self._preview_job, self._status_job, self._plot_job, self.help_hide_job):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        self.hide_help()
        self.destroy()

    # ------------------------------------------------------------------
    # الشرح عند الضغط بزر الفأرة الأيمن
    # ------------------------------------------------------------------
    @staticmethod
    def _help_targets(widget):
        targets = [widget]
        buttons = getattr(widget, "_buttons_dict", None)
        if isinstance(buttons, dict):
            targets.extend(buttons.values())
        return targets

    def add_help(self, widget, title, body):
        def handler(event, t=title, b=body):
            self.show_help(t, b)
            return "break"

        for target in self._help_targets(widget):
            for seq in ("<Button-3>", "<Button-2>"):
                try:
                    target.bind(seq, handler, add="+")
                except Exception:
                    pass

    def show_help(self, title, body):
        self.hide_help()
        dpi = self._dpi_scale()
        scale = self._font_scale
        dark = ctk.get_appearance_mode() == "Dark"
        bg, fg = ("#1f2937", "#f3f4f6") if dark else ("#ffffff", "#111827")
        accent, border, muted = ("#7cb7ff", "#4b5563", "#9ca3af") if dark else ("#1d4ed8", "#9ca3af", "#6b7280")
        pop = tk.Toplevel(self)
        pop.withdraw()
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        outer = tk.Frame(pop, bg=border, padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg=bg, padx=int(14 * dpi), pady=int(10 * dpi))
        inner.pack()

        def mk_font(px, weight="normal"):
            return tkfont.Font(root=self, family=self.font_family or "TkDefaultFont",
                               size=-max(10, int(px * scale * dpi)), weight=weight)

        wrap = int(330 * dpi)
        tk.Label(inner, text=title, bg=bg, fg=accent, font=mk_font(16, "bold"), justify="right",
                 anchor="e", wraplength=wrap).pack(fill="x")
        tk.Label(inner, text=body, bg=bg, fg=fg, font=mk_font(14), justify="right",
                 anchor="e", wraplength=wrap).pack(fill="x", pady=(int(4 * dpi), 0))
        tk.Label(inner, text="اضغط في أي مكان لإغلاق الشرح", bg=bg, fg=muted, font=mk_font(11),
                 justify="right", anchor="e").pack(fill="x", pady=(int(6 * dpi), 0))
        pop.update_idletasks()
        w, h = pop.winfo_reqwidth(), pop.winfo_reqheight()
        px, py = self.winfo_pointerxy()
        x = max(4, min(px + 14, self.winfo_screenwidth() - w - 8))
        y = py + 16
        if y + h > self.winfo_screenheight() - 8:
            y = max(4, py - h - 10)
        pop.geometry(f"+{x}+{y}")
        pop.deiconify()
        pop.lift()
        pop.bind("<Button-1>", self.hide_help)
        self.help_popup = pop
        self.help_hide_job = self.after(7000, self.hide_help)

    def hide_help(self, event=None):
        if self.help_hide_job:
            try:
                self.after_cancel(self.help_hide_job)
            except Exception:
                pass
            self.help_hide_job = None
        if self.help_popup is not None:
            try:
                self.help_popup.destroy()
            except Exception:
                pass
            self.help_popup = None

    # ------------------------------------------------------------------
    # بناء الواجهة
    # ------------------------------------------------------------------
    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- الشريط العلوي: الشاشة + وحدة الزوايا + أدوات
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        top.grid_columnconfigure(0, weight=1)

        self.display_var = ctk.StringVar(value="")
        self.display = ctk.CTkEntry(top, textvariable=self.display_var, font=self.fonts["display"],
                                    justify="right", height=64)
        self.display.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.display_var.trace_add("write", self.on_display_changed)
        self.add_help(self.display, "شاشة العرض",
                      "اكتب بلوحة المفاتيح أو بالأزرار. يمكنك النقر داخل الشاشة لتعديل أي موضع، ولصق عملية نسخها (Ctrl+V). "
                      "يظهر ناتج تقديري تحت الشاشة أثناء الكتابة.")

        self.angle_var = ctk.StringVar(value="درجات" if self.angle_mode == "Degrees" else "راديان")
        self.angle_seg = ctk.CTkSegmentedButton(top, values=["راديان", "درجات"], variable=self.angle_var,
                                                command=self.set_angle_mode, font=self.fonts["small_btn"])
        self.angle_seg.grid(row=0, column=1, padx=4)
        self.add_help(self.angle_seg, "وحدة الزوايا",
                      "اختر راديان أو درجات لدوال sin و cos و tan ومعكوساتها. ينطبق الاختيار على الحساب والمشتقات والرسم.")

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=2, padx=(4, 0))
        self.theme_btn = self._tool_button(tools, "🌓 الثيم", self.toggle_theme, 0,
                                           "تبديل المظهر", "يبدّل بين المظهر الداكن والفاتح ويحفظ اختيارك.")
        self._tool_button(tools, "❓ الدليل", self.show_guide, 1,
                          "دليل الاستخدام", "يعرض شرحًا لكل الميزات: الدوال والمعادلات والرسم والمحولات والاختصارات.")
        self._tool_button(tools, "ℹ️ حول", self.show_about, 2,
                          "حول البرنامج", "يعرض معلومات الإصدار والمطور ووسيلة التواصل.")

        # --- سطر المعاينة (ناتج تقديري / رسائل الخطأ)
        self.preview_label = ctk.CTkLabel(self, text="", anchor="e", font=self.fonts["body"], text_color=MUTED)
        self.preview_label.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 2))

        # --- التبويبات
        self.tabview = ctk.CTkTabview(self, command=self.on_tab_change)
        self.tabview.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 4))
        try:
            self.tabview._segmented_button.configure(font=self.fonts["tab"])
        except Exception:
            pass
        self.tab_calc = self.tabview.add(TAB_CALC)
        self.tab_graph = self.tabview.add(TAB_GRAPH)
        self.tab_conv = self.tabview.add(TAB_CONV)
        self.add_help(self.tabview._segmented_button, "التبويبات",
                      "الحاسبة العلمية، الرسم البياني للدوال، ومحولات العملات والوحدات. اضغط على التبويب للانتقال إليه.")

        self.setup_calculator_tab()
        self.setup_graph_tab()
        self.setup_converter_tab()

        # --- شريط الحالة
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 6))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="💡 اضغط بزر الفأرة الأيمن على أي زر أو عنصر لمعرفة وظيفته",
                     font=self.fonts["small"], text_color=MUTED, anchor="e").grid(row=0, column=0, sticky="e")
        self.status_label = ctk.CTkLabel(bar, text="", font=self.fonts["small"], text_color=OK_COLOR, anchor="w")
        self.status_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        bar.grid_columnconfigure(0, weight=1)

    def _tool_button(self, parent, text, command, col, title, body):
        btn = ctk.CTkButton(parent, text=text, command=command, width=78, height=34, font=self.fonts["small_btn"],
                            fg_color=KEY_STYLES["tool"][0], hover_color=KEY_STYLES["tool"][1],
                            text_color=KEY_STYLES["tool"][2])
        btn.grid(row=0, column=col, padx=3)
        self.add_help(btn, title, body)
        return btn

    def make_key(self, parent, label, role, command, row, col, colspan=1, help_key=None, font="btn"):
        bg, hover, fg = KEY_STYLES[role]
        btn = ctk.CTkButton(parent, text=label, command=command, height=28, corner_radius=8,
                            fg_color=bg, hover_color=hover, text_color=fg, font=self.fonts[font])
        btn.grid(row=row, column=col, columnspan=colspan, padx=3, pady=3, sticky="nsew")
        title, body = HELP.get(help_key or label, ("زر", "يُدخل هذا الرمز في الشاشة."))
        self.add_help(btn, title, body)
        return btn

    # ------------------------------------------------------------------
    # تبويب الحاسبة
    # ------------------------------------------------------------------
    def setup_calculator_tab(self):
        tab = self.tab_calc
        tab.grid_columnconfigure(0, weight=4)
        tab.grid_columnconfigure(1, weight=1, minsize=170)
        tab.grid_rowconfigure(0, weight=1)

        pad = ctk.CTkFrame(tab, fg_color="transparent")
        pad.grid(row=0, column=0, sticky="nsew")
        for r in range(8):
            pad.grid_rowconfigure(r, weight=1, uniform="krow")
        for c in range(6):
            pad.grid_columnconfigure(c, weight=1, uniform="kcol")

        ins = self.insert_text
        K = self.make_key
        K(pad, "MC", "mem", self.memory_clear, 0, 0)
        K(pad, "MR", "mem", self.memory_recall, 0, 1)
        K(pad, "M+", "mem", self.memory_add, 0, 2)
        K(pad, "M−", "mem", self.memory_sub, 0, 3)
        K(pad, "⌫", "back", self.backspace, 0, 4)
        K(pad, "C", "clear", self.clear, 0, 5)

        for c, (lbl, text) in enumerate([("sin", "sin("), ("cos", "cos("), ("tan", "tan("),
                                         ("ln", "ln("), ("log", "log("), ("√", "sqrt(")]):
            K(pad, lbl, "func", lambda t=text: ins(t), 1, c)
        K(pad, "asin", "func", lambda: ins("asin("), 2, 0)
        K(pad, "acos", "func", lambda: ins("acos("), 2, 1)
        K(pad, "atan", "func", lambda: ins("atan("), 2, 2)
        K(pad, "π", "func", lambda: ins("π"), 2, 3)
        K(pad, "e", "func", lambda: ins("e", smart_e=True), 2, 4)
        K(pad, "n!", "func", lambda: ins("fact("), 2, 5)

        K(pad, "x", "calc", lambda: ins("x"), 3, 0)
        K(pad, "x = ؟", "calc", lambda: ins("="), 3, 1, font="small_btn")
        K(pad, "d/dx", "calc", self.derivative, 3, 2)
        K(pad, "∫dx", "calc", self.integral, 3, 3)
        K(pad, "1/x", "func", lambda: self.wrap_expression("(", ")^(-1)"), 3, 4)
        K(pad, "x²", "func", lambda: self.wrap_expression("(", ")^2"), 3, 5)

        rows = [
            [("7", "num"), ("8", "num"), ("9", "num"), ("÷", "op"), ("(", "op"), (")", "op")],
            [("4", "num"), ("5", "num"), ("6", "num"), ("×", "op"), ("%", "op"), ("^", "op")],
            [("1", "num"), ("2", "num"), ("3", "num"), ("−", "op")],
            [("0", "num"), (".", "num"), ("00", "num"), ("+", "op")],
        ]
        for i, row in enumerate(rows):
            for c, (lbl, role) in enumerate(row):
                K(pad, lbl, role, lambda t=lbl: ins(t), 4 + i, c)
        K(pad, "📈 ارسم", "plot", self.switch_and_plot, 6, 4, colspan=2, help_key="plot")
        K(pad, "=", "equals", self.calculate, 7, 4, colspan=2)

        # --- السجل والذاكرة
        hist = ctk.CTkFrame(tab)
        hist.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        hist.grid_columnconfigure(0, weight=1)
        hist.grid_rowconfigure(1, weight=1)
        lbl = ctk.CTkLabel(hist, text="🕘 السجل", font=self.fonts["section"])
        lbl.grid(row=0, column=0, pady=(8, 4))
        self.history_box = ctk.CTkTextbox(hist, width=150, font=self.fonts["small"], wrap="word")
        self.history_box.grid(row=1, column=0, padx=8, pady=4, sticky="nsew")
        self.history_box.configure(state="disabled")
        self.history_box.tag_config("rtl", justify="right")
        self.history_box.bind("<Double-Button-1>", self.on_history_double_click, add="+")
        self.add_help(self.history_box, "سجل العمليات",
                      "يحفظ كل العمليات والتحويلات. انقر نقرًا مزدوجًا على أي عملية لإعادة نتيجتها إلى الشاشة.")
        self.mem_label = ctk.CTkLabel(hist, text="الذاكرة: 0", font=self.fonts["small"], text_color=MUTED)
        self.mem_label.grid(row=2, column=0, pady=2)
        self.add_help(self.mem_label, "مؤشر الذاكرة", "يعرض القيمة المحفوظة حاليًا في الذاكرة (MC / MR / M+ / M−).")
        clear_btn = ctk.CTkButton(hist, text="🗑️ مسح السجل", command=self.clear_history, height=32,
                                  fg_color=KEY_STYLES["clear"][0], hover_color=KEY_STYLES["clear"][1],
                                  text_color=KEY_STYLES["clear"][2], font=self.fonts["small_btn"])
        clear_btn.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="ew")
        self.add_help(clear_btn, "مسح السجل", "يحذف كل العمليات المعروضة في السجل. لا يؤثر على الذاكرة.")

    # ------------------------------------------------------------------
    # تبويب الرسم
    # ------------------------------------------------------------------
    def setup_graph_tab(self):
        tab = self.tab_graph
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        r0 = ctk.CTkFrame(tab, fg_color="transparent")
        r0.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        r0.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(r0, text="f(x) =", font=self.fonts["bold"]).grid(row=0, column=0, padx=(0, 6))
        self.graph_entry = ctk.CTkEntry(r0, font=self.fonts["body"], height=36,
                                        placeholder_text="مثال: sin(x) ؛ x^2/10 ؛ y = 2x + 1")
        self.graph_entry.grid(row=0, column=1, sticky="ew")
        self.graph_entry.insert(0, "sin(x)")
        self._return_handlers[self.graph_entry._entry] = self.plot_graph
        self.add_help(self.graph_entry, "كتابة الدالة",
                      "اكتب دالة بدلالة x. للرسم المتعدد افصل بين الدوال بفاصلة منقوطة (;) حتى 6 دوال. "
                      "إذا كتبت معادلة مثل x^2 = x + 2 رُسم طرفاها لترى نقاط التقاطع (الحلول).")
        b = ctk.CTkButton(r0, text="📈 ارسم", command=self.plot_graph, width=90, height=36, font=self.fonts["btn"])
        b.grid(row=0, column=2, padx=(6, 0))
        self.add_help(b, "ارسم", "يرسم الدالة المكتوبة ضمن حدود x المحددة. (اختصار: Enter)")

        r1 = ctk.CTkFrame(tab, fg_color="transparent")
        r1.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(r1, text="من x:", font=self.fonts["body"]).grid(row=0, column=0, padx=(0, 4))
        self.x_min_entry = ctk.CTkEntry(r1, width=72, font=self.fonts["body"], justify="center")
        self.x_min_entry.insert(0, "-10")
        self.x_min_entry.grid(row=0, column=1, padx=(0, 10))
        ctk.CTkLabel(r1, text="إلى x:", font=self.fonts["body"]).grid(row=0, column=2, padx=(0, 4))
        self.x_max_entry = ctk.CTkEntry(r1, width=72, font=self.fonts["body"], justify="center")
        self.x_max_entry.insert(0, "10")
        self.x_max_entry.grid(row=0, column=3, padx=(0, 10))
        for e in (self.x_min_entry, self.x_max_entry):
            self._return_handlers[e._entry] = self.plot_graph
        self.add_help(self.x_min_entry, "بداية النطاق", "أصغر قيمة x ستُرسم. يمكنك كتابة عمليات مثل -2*pi.")
        self.add_help(self.x_max_entry, "نهاية النطاق", "أكبر قيمة x ستُرسم. يجب أن تكون أكبر من البداية.")
        rb = ctk.CTkButton(r1, text="⟲ إعادة الضبط", command=self.reset_view, height=32, font=self.fonts["small_btn"],
                           fg_color=KEY_STYLES["tool"][0], hover_color=KEY_STYLES["tool"][1],
                           text_color=KEY_STYLES["tool"][2])
        rb.grid(row=0, column=4, padx=3)
        self.add_help(rb, "إعادة الضبط", "يعيد عرض الرسم إلى نطاق x المكتوب مع ضبط محور y تلقائيًا. (نقر مزدوج على الرسم يفعل نفس الشيء)")
        sb = ctk.CTkButton(r1, text="💾 حفظ صورة", command=self.save_plot_image, height=32, font=self.fonts["small_btn"],
                           fg_color=KEY_STYLES["tool"][0], hover_color=KEY_STYLES["tool"][1],
                           text_color=KEY_STYLES["tool"][2])
        sb.grid(row=0, column=5, padx=3)
        self.add_help(sb, "حفظ صورة", "يحفظ الرسم الحالي كصورة PNG أو ملف PDF.")

        self.graph_container = ctk.CTkFrame(tab, fg_color=("#f2f2f2", "#242424"))
        self.graph_container.grid(row=2, column=0, sticky="nsew")
        self.graph_container.grid_rowconfigure(0, weight=1)
        self.graph_container.grid_columnconfigure(0, weight=1)
        try:
            self.fig = Figure(figsize=(6, 4), dpi=100, layout="constrained")
        except TypeError:
            self.fig = Figure(figsize=(6, 4), dpi=100, constrained_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_container)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.grid(row=0, column=0, sticky="nsew")
        self.canvas_widget.bind("<Configure>", self.on_plot_resize, add="+")
        self.add_help(self.canvas_widget, "منطقة الرسم",
                      "عجلة الفأرة: تكبير/تصغير عند المؤشر.  السحب بالزر الأيسر: تحريك الرسم.  "
                      "نقر مزدوج: إعادة الضبط.  حرّك المؤشر لقراءة الإحداثيات.")
        self.canvas.mpl_connect("scroll_event", self.on_plot_scroll)
        self.canvas.mpl_connect("button_press_event", self.on_plot_press)
        self.canvas.mpl_connect("button_release_event", self.on_plot_release)
        self.canvas.mpl_connect("motion_notify_event", self.on_plot_motion)

        r3 = ctk.CTkFrame(tab, fg_color="transparent")
        r3.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        r3.grid_columnconfigure(1, weight=1)
        self.coord_label = ctk.CTkLabel(r3, text="", font=self.fonts["small"], text_color=MUTED, anchor="w", width=170)
        self.coord_label.grid(row=0, column=0, sticky="w")
        self.graph_status = ctk.CTkLabel(r3, text="عجلة الفأرة للتكبير · اسحب للتحريك · نقر مزدوج لإعادة الضبط",
                                         font=self.fonts["small"], text_color=MUTED, anchor="e")
        self.graph_status.grid(row=0, column=1, sticky="e")
        self.style_axes()

    # ------------------------------------------------------------------
    # تبويب المحولات
    # ------------------------------------------------------------------
    def _card(self, parent, col, title):
        card = ctk.CTkFrame(parent)
        card.grid(row=0, column=col, sticky="nsew", padx=6, pady=2)
        card.grid_columnconfigure((0, 1, 2), weight=1, uniform="cc")
        ctk.CTkLabel(card, text=title, font=self.fonts["section"]).grid(row=0, column=0, columnspan=3, pady=(10, 6))
        return card

    def setup_converter_tab(self):
        tab = self.tab_conv
        tab.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        tab.grid_rowconfigure(0, weight=1)

        # ---- العملات
        cur = self._card(tab, 0, "💱 محول العملات")
        self.cur_amount = ctk.CTkEntry(cur, font=self.fonts["bold"], height=36, justify="center",
                                       placeholder_text="المبلغ")
        self.cur_amount.grid(row=1, column=0, columnspan=3, padx=10, pady=4, sticky="ew")
        self.cur_amount.insert(0, "1")
        self._return_handlers[self.cur_amount._entry] = lambda: self.update_currency_result(log=True)
        self.cur_amount.bind("<KeyRelease>", lambda e: self.update_currency_result(), add="+")
        self.add_help(self.cur_amount, "المبلغ", "اكتب المبلغ المراد تحويله (تقبل عمليات مثل 150*3). اضغط Enter لتسجيل التحويل في السجل.")
        labels = [currency_label(c) for c in CURRENCIES]
        self.from_currency = ctk.StringVar(value=currency_label("USD"))
        self.to_currency = ctk.StringVar(value=currency_label("SAR"))
        self.from_curr_menu = ctk.CTkOptionMenu(cur, values=labels, variable=self.from_currency, font=self.fonts["small"],
                                                dropdown_font=self.fonts["small"], command=lambda v: self.update_currency_result())
        self.from_curr_menu.grid(row=2, column=0, padx=(10, 3), pady=4, sticky="ew")
        sw = ctk.CTkButton(cur, text="⇄", command=self.swap_currency, width=40, height=30, font=self.fonts["btn"])
        sw.grid(row=2, column=1, pady=4)
        self.to_curr_menu = ctk.CTkOptionMenu(cur, values=labels, variable=self.to_currency, font=self.fonts["small"],
                                              dropdown_font=self.fonts["small"], command=lambda v: self.update_currency_result())
        self.to_curr_menu.grid(row=2, column=2, padx=(3, 10), pady=4, sticky="ew")
        self.add_help(self.from_curr_menu, "من عملة", "اختر العملة التي تملك المبلغ بها.")
        self.add_help(self.to_curr_menu, "إلى عملة", "اختر العملة التي تريد التحويل إليها.")
        self.add_help(sw, "تبديل", "يعكس العملتين: المصدر يصبح الهدف والعكس.")
        self.cur_result = ctk.CTkLabel(cur, text="—", font=self.fonts["result"], text_color=OK_COLOR)
        self.cur_result.grid(row=3, column=0, columnspan=3, pady=(8, 0))
        self.add_help(self.cur_result, "النتيجة", "ناتج التحويل بحسب أسعار الصرف المحفوظة. يتحدث فورًا أثناء الكتابة.")
        self.cur_rate_label = ctk.CTkLabel(cur, text="", font=self.fonts["small"], text_color=MUTED)
        self.cur_rate_label.grid(row=4, column=0, columnspan=3)
        ba = ctk.CTkButton(cur, text="📋 نسخ", command=lambda: self.copy_text(self.cur_result.cget("text")),
                           height=30, font=self.fonts["small_btn"])
        ba.grid(row=5, column=0, padx=(10, 3), pady=(6, 3), sticky="ew")
        bb = ctk.CTkButton(cur, text="↗ للحاسبة", command=lambda: self.send_to_calc(self._last_currency_value),
                           height=30, font=self.fonts["small_btn"])
        bb.grid(row=5, column=1, columnspan=2, padx=(3, 10), pady=(6, 3), sticky="ew")
        self.add_help(ba, "نسخ النتيجة", "ينسخ النتيجة مع رمز العملة إلى الحافظة.")
        self.add_help(bb, "إرسال للحاسبة", "ينقل الرقم الناتج إلى شاشة الحاسبة لتكمل عليه حسابًا.")
        self.refresh_btn = ctk.CTkButton(cur, text="🌐 تحديث الأسعار", command=self.refresh_rates_async, height=32,
                                         fg_color="#356a8a", hover_color="#2b566f", font=self.fonts["small_btn"])
        self.refresh_btn.grid(row=6, column=0, columnspan=2, padx=(10, 3), pady=3, sticky="ew")
        self.edit_rates_btn = ctk.CTkButton(cur, text="⚙️ تعديل", command=self.edit_rates, height=32,
                                            fg_color="#b45309", hover_color="#92400e", font=self.fonts["small_btn"])
        self.edit_rates_btn.grid(row=6, column=2, padx=(3, 10), pady=3, sticky="ew")
        self.add_help(self.refresh_btn, "تحديث الأسعار", "يجلب أحدث أسعار مرجعية من الإنترنت ويحفظها. "
                      "الأسعار مرجعية وليست عروض بيع وشراء لحظية. العملات المُثبَّتة يدويًا لا تتغير.")
        self.add_help(self.edit_rates_btn, "تعديل الأسعار", "يتيح كتابة سعر أي عملة يدويًا (مفيد للريال اليمني لاختلاف السعر بين المناطق) وتثبيته.")
        self.rates_status = ctk.CTkLabel(cur, text="", font=self.fonts["small"], wraplength=300, justify="center")
        self.rates_status.grid(row=7, column=0, columnspan=3, padx=8, pady=(4, 0))
        credit = ctk.CTkLabel(cur, text=RATES_CREDIT_TEXT, font=self.fonts["small"], text_color=("#1d4ed8", "#7cb7ff"),
                              cursor="hand2")
        credit.grid(row=8, column=0, columnspan=3, pady=(0, 8))
        credit.bind("<Button-1>", lambda e: webbrowser.open(RATES_CREDIT_URL), add="+")
        self.add_help(credit, "مصدر الأسعار", "اضغط بزر الفأرة الأيسر لفتح موقع مزوّد الأسعار.")
        self._last_currency_value = ""

        # ---- الوحدات
        unit = self._card(tab, 1, "📏 محول الوحدات")
        self.unit_category = ctk.StringVar(value="الطول")
        self.category_menu = ctk.CTkOptionMenu(unit, values=list(UNIT_CATEGORIES), variable=self.unit_category,
                                               font=self.fonts["body"], dropdown_font=self.fonts["body"],
                                               command=self.on_category_change)
        self.category_menu.grid(row=1, column=0, columnspan=3, padx=10, pady=4, sticky="ew")
        self.add_help(self.category_menu, "نوع الوحدة", "اختر الفئة: طول، وزن، مساحة، حجم، سرعة، أو حرارة.")
        self.unit_amount = ctk.CTkEntry(unit, font=self.fonts["bold"], height=36, justify="center", placeholder_text="القيمة")
        self.unit_amount.grid(row=2, column=0, columnspan=3, padx=10, pady=4, sticky="ew")
        self.unit_amount.insert(0, "1")
        self._return_handlers[self.unit_amount._entry] = lambda: self.update_unit_result(log=True)
        self.unit_amount.bind("<KeyRelease>", lambda e: self.update_unit_result(), add="+")
        self.add_help(self.unit_amount, "القيمة", "اكتب القيمة المراد تحويلها (تقبل عمليات حسابية). اضغط Enter لتسجيل التحويل في السجل.")
        self.from_unit = ctk.StringVar()
        self.to_unit = ctk.StringVar()
        self.from_unit_menu = ctk.CTkOptionMenu(unit, values=[""], variable=self.from_unit, font=self.fonts["small"],
                                                dropdown_font=self.fonts["small"], command=lambda v: self.update_unit_result())
        self.from_unit_menu.grid(row=3, column=0, padx=(10, 3), pady=4, sticky="ew")
        usw = ctk.CTkButton(unit, text="⇄", command=self.swap_units, width=40, height=30, font=self.fonts["btn"])
        usw.grid(row=3, column=1, pady=4)
        self.to_unit_menu = ctk.CTkOptionMenu(unit, values=[""], variable=self.to_unit, font=self.fonts["small"],
                                              dropdown_font=self.fonts["small"], command=lambda v: self.update_unit_result())
        self.to_unit_menu.grid(row=3, column=2, padx=(3, 10), pady=4, sticky="ew")
        self.add_help(self.from_unit_menu, "من وحدة", "اختر وحدة القيمة الحالية.")
        self.add_help(self.to_unit_menu, "إلى وحدة", "اختر الوحدة التي تريد التحويل إليها.")
        self.add_help(usw, "تبديل", "يعكس وحدة المصدر ووحدة الهدف.")
        self.unit_result = ctk.CTkLabel(unit, text="—", font=self.fonts["result"], text_color=OK_COLOR)
        self.unit_result.grid(row=4, column=0, columnspan=3, pady=(8, 0))
        self.add_help(self.unit_result, "النتيجة", "ناتج التحويل. يتحدث فورًا أثناء الكتابة.")
        self._last_unit_value = ""
        self.unit_caption = ctk.CTkLabel(unit, text="", font=self.fonts["small"], text_color=MUTED)
        self.unit_caption.grid(row=5, column=0, columnspan=3)
        ua = ctk.CTkButton(unit, text="📋 نسخ", command=lambda: self.copy_text(self.unit_result.cget("text")),
                           height=30, font=self.fonts["small_btn"])
        ua.grid(row=6, column=0, padx=(10, 3), pady=(6, 3), sticky="ew")
        ub = ctk.CTkButton(unit, text="↗ للحاسبة", command=lambda: self.send_to_calc(self._last_unit_value),
                           height=30, font=self.fonts["small_btn"])
        ub.grid(row=6, column=1, columnspan=2, padx=(3, 10), pady=(6, 3), sticky="ew")
        self.add_help(ua, "نسخ النتيجة", "ينسخ النتيجة مع الوحدة إلى الحافظة.")
        self.add_help(ub, "إرسال للحاسبة", "ينقل الرقم الناتج إلى شاشة الحاسبة.")
        self.on_category_change("الطول")
        self.update_rates_status()
        self.update_currency_result()

    # ==================================================================
    # الخطوط والتجاوب مع تغيير الحجم
    # ==================================================================
    def on_window_configure(self, event):
        if event.widget is not self:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(90, self.apply_layout_scale)

    def apply_layout_scale(self):
        self._resize_job = None
        if self._closing:
            return
        w, h = self.winfo_width(), self.winfo_height()
        try:
            logical = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            logical = 1.0
        w, h = w / max(logical, 0.1), h / max(logical, 0.1)
        scale = clamp(min(w / 1100.0, h / 720.0), 0.74, 1.5)
        if abs(scale - self._font_scale) >= 0.03:
            self._font_scale = scale
            for name, (size, _) in FONT_SPECS.items():
                self.fonts[name].configure(size=max(9, int(round(size * scale))))
            try:
                self.display.configure(height=int(64 * clamp(scale, 0.85, 1.3)))
            except Exception:
                pass
        self.update_display_font()

    def update_display_font(self):
        base = FONT_SPECS["display"][0] * self._font_scale
        text = self.display_var.get()
        try:
            width = self.display.winfo_width() / max(self._dpi_scale(), 0.5)
        except tk.TclError:
            width = 400
        n = max(len(text), 1)
        fit = (width - 28) / (0.62 * n)
        self.fonts["display"].configure(size=int(clamp(min(base, fit), 15, 120)))

    # ==================================================================
    # الشاشة والإدخال
    # ==================================================================
    def on_display_changed(self, *_):
        self.update_display_font()
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(140, self.update_preview)

    def get_input(self) -> str:
        return re.sub(r"\s*\+\s*C\s*$", "", self.display_var.get()).strip()

    def set_display(self, text: str, result: bool = False, chainable: bool = False):
        self.display.delete(0, "end")
        self.display.insert(0, text)
        self.display.icursor("end")
        self.result_shown = result
        self.result_chainable = chainable

    def set_preview(self, text: str, error: bool = False):
        self.preview_label.configure(text=text, text_color=ERR_COLOR if error else MUTED)

    def update_preview(self):
        self._preview_job = None
        text = self.get_input()
        if not text or self.result_shown or "=" in text:
            self.set_preview("")
            return
        try:
            expr = parse_expression(text, self.angle_mode)
            if expr.free_symbols:
                self.set_preview("")
                return
            val = format_value(expr)
            self.set_preview("" if val == text else f"= {val}")
        except Exception:
            self.set_preview("")

    def insert_text(self, s: str, smart_e: bool = False):
        entry = self.display
        if self.result_shown:
            if not (self.result_chainable and s and s[0] in "+-*/^%×÷−"):
                self.display.delete(0, "end")
            else:
                entry.icursor("end")
            self.result_shown = False
        pos = entry.index("insert")
        if smart_e and pos > 0 and (entry.get()[pos - 1].isdigit() or entry.get()[pos - 1] == ")"):
            s = "*e"
        entry.insert(pos, s)
        entry.icursor(pos + len(s))
        entry.focus_set()
        self.set_preview("")

    def wrap_expression(self, left: str, right: str):
        text = self.get_input()
        if not text:
            return
        def outer_wrapped(t):
            if not (t.startswith("(") and t.endswith(")")):
                return False
            depth = 0
            for i, ch in enumerate(t):
                depth += (ch == "(") - (ch == ")")
                if depth == 0 and i < len(t) - 1:
                    return False
            return depth == 0

        if re.fullmatch(r"[\d.]+|[A-Za-zπ]+", text) or outer_wrapped(text):
            new = text + right.lstrip(")")
        else:
            new = left + text + right
        self.set_display(new)
        self.set_preview("")

    def clear(self):
        self.set_display("")
        self.set_preview("")
        self.display.focus_set()

    def backspace(self):
        if self.result_shown and not self.result_chainable:
            self.clear()
            return
        self.result_shown = False
        pos = self.display.index("insert")
        if pos > 0:
            self.display.delete(pos - 1, pos)
        self.display.focus_set()

    def set_angle_mode(self, choice):
        self.angle_mode = "Degrees" if choice == "درجات" else "Radians"
        self.update_preview()
        if self.tabview.get() == TAB_GRAPH and self._plot_ready:
            self.plot_graph()

    def flash_status(self, msg: str, error: bool = False):
        self.status_label.configure(text=msg, text_color=ERR_COLOR if error else OK_COLOR)
        if self._status_job:
            self.after_cancel(self._status_job)
        self._status_job = self.after(3500, lambda: self.status_label.configure(text=""))

    def copy_text(self, text: str):
        if not text or text == "—":
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.flash_status("تم النسخ ✓")

    def send_to_calc(self, value: str):
        if not value:
            return
        self.set_display(value, result=True, chainable=True)
        self.tabview.set(TAB_CALC)
        self.display.focus_set()

    # ==================================================================
    # الحسابات (غير المتزامنة للعمليات الثقيلة)
    # ==================================================================
    def run_job(self, func, on_done, timeout=15.0):
        self._job_id += 1
        jid = self._job_id
        self._jobs[jid] = on_done
        self._job_deadline = time.monotonic() + timeout

        def worker():
            try:
                res = ("ok", func())
            except MathError as exc:
                res = ("err", str(exc))
            except RecursionError:
                res = ("err", "التعبير معقد جدًا")
            except Exception as exc:  # noqa: BLE001
                res = ("err", f"تعذر الحساب ({type(exc).__name__})")
            self._job_queue.put((jid, res))

        threading.Thread(target=worker, daemon=True, name="calc-job").start()
        self.set_preview("⏳ جارٍ الحساب…")
        self.after(40, self.poll_jobs)

    def poll_jobs(self):
        if self._closing:
            return
        try:
            while True:
                jid, res = self._job_queue.get_nowait()
                cb = self._jobs.pop(jid, None)
                if cb and jid == self._job_id:
                    cb(res)
        except queue.Empty:
            pass
        active = self._job_id in self._jobs
        if active and time.monotonic() > self._job_deadline:
            cb = self._jobs.pop(self._job_id)
            self._job_id += 1       # تجاهل النتيجة المتأخرة
            cb(("err", "استغرقت العملية وقتًا طويلًا. جرّب تعبيرًا أبسط."))
        elif active:
            self.after(40, self.poll_jobs)

    def finish_result(self, source: str, text: str, chainable: bool, history: bool = True):
        self.set_display(text, result=True, chainable=chainable)
        self.set_preview("")
        if history:
            self.add_history(source, text)

    def show_error(self, msg: str):
        self.set_preview(f"⚠ {msg}", error=True)

    def calculate(self):
        src = self.get_input()
        if not src:
            return
        mode = self.angle_mode
        if "=" in src.translate(_TRANSLATE):
            self.run_job(lambda: evaluate_text(src, mode), lambda r: self._calc_done(src, r))
            return
        try:
            text, chain = evaluate_text(src, mode)
        except MathError as exc:
            self.show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"تعذر الحساب ({type(exc).__name__})")
            return
        self.finish_result(src, text, chain)

    def _calc_done(self, src, res):
        if res[0] == "ok":
            text, chain = res[1]
            self.finish_result(src, text, chain)
        else:
            self.show_error(res[1])

    def derivative(self):
        src = self.get_input()
        if not src:
            return
        mode = self.angle_mode
        self.run_job(lambda: derivative_text(src, mode), lambda r: self._calculus_done(f"d/dx({src})", r))

    def integral(self):
        src = self.get_input()
        if not src:
            return
        mode = self.angle_mode
        self.run_job(lambda: integral_text(src, mode), lambda r: self._calculus_done(f"∫({src})dx", r))

    def _calculus_done(self, label, res):
        if res[0] == "ok":
            self.finish_result(label, res[1], chainable=False)
            if res[1].endswith(" + C"):
                self.display_var.set(res[1])
        else:
            self.show_error(res[1])

    # ------------------------------------------------------------------
    # الذاكرة والسجل
    # ------------------------------------------------------------------
    def current_number(self):
        val = parse_amount(self.get_input())
        if val is None:
            self.show_error("أدخل قيمة رقمية صالحة أولًا")
        return val

    def update_mem_label(self):
        self.mem_label.configure(text=f"الذاكرة: {format_number(self.memory)}")

    def memory_add(self):
        val = self.current_number()
        if val is not None:
            self.memory += val
            self.update_mem_label()

    def memory_sub(self):
        val = self.current_number()
        if val is not None:
            self.memory -= val
            self.update_mem_label()

    def memory_recall(self):
        self.insert_text(format_number(self.memory))

    def memory_clear(self):
        self.memory = 0.0
        self.update_mem_label()

    def add_history(self, expr: str, result: str):
        self.history_items.append((expr, result))
        if len(self.history_items) > 300:
            self.history_items = self.history_items[-300:]
            self.refresh_history()
            return
        self._append_history_line(expr, result)

    def _append_history_line(self, expr, result):
        self.history_box.configure(state="normal")
        self.history_box.insert("end", f"{expr}\n= {result}\n\n", "rtl")
        self.history_box.configure(state="disabled")
        self.history_box.see("end")

    def refresh_history(self):
        self.history_box.configure(state="normal")
        self.history_box.delete("1.0", "end")
        self.history_box.configure(state="disabled")
        for e, r in self.history_items:
            self._append_history_line(e, r)

    def clear_history(self):
        self.history_items.clear()
        self.refresh_history()

    def on_history_double_click(self, event):
        try:
            line = int(str(self.history_box.index("current")).split(".")[0])
        except (ValueError, tk.TclError):
            return
        idx = (line - 1) // 3
        if 0 <= idx < len(self.history_items):
            result = self.history_items[idx][1]
            if not result.startswith("x") and "؛" not in result:
                self.set_display(re.sub(r"\s*\+\s*C$", "", result), result=True, chainable=True)
                self.display.focus_set()

    # ==================================================================
    # الرسم البياني
    # ==================================================================
    def graph_colors(self):
        dark = ctk.get_appearance_mode() == "Dark"
        return {
            "fig": "#242424" if dark else "#f2f2f2",
            "ax": "#1b1b1b" if dark else "#ffffff",
            "text": "#e6e6e6" if dark else "#222222",
            "grid": "#ffffff" if dark else "#000000",
            "axis": "#8a8f98" if dark else "#555555",
            "curves": PLOT_COLORS_DARK if dark else PLOT_COLORS_LIGHT,
        }

    def style_axes(self):
        c = self.graph_colors()
        s = self._plot_scale
        self.fig.set_facecolor(c["fig"])
        self.canvas_widget.configure(bg=c["fig"])
        ax = self.ax
        ax.set_facecolor(c["ax"])
        ax.tick_params(colors=c["text"], labelsize=10 * s)
        for spine in ax.spines.values():
            spine.set_color(c["axis"])
        ax.grid(True, linestyle="--", alpha=0.25, color=c["grid"])
        ax.axhline(0, color=c["axis"], linewidth=1.1)
        ax.axvline(0, color=c["axis"], linewidth=1.1)
        ax.set_xlabel("x", color=c["text"], fontsize=11 * s)
        ax.set_ylabel("f(x)", color=c["text"], fontsize=11 * s)

    def on_plot_resize(self, event):
        if event.width < 20 or event.height < 20:
            return
        scale = clamp(min(event.width / 700.0, event.height / 440.0), 0.75, 1.45)
        if abs(scale - self._plot_scale) >= 0.05:
            self._plot_scale = scale
            if self._plot_job:
                self.after_cancel(self._plot_job)
            self._plot_job = self.after(60, self.render_plot)

    def _read_x_range(self):
        lo, hi = parse_amount(self.x_min_entry.get()), parse_amount(self.x_max_entry.get())
        if lo is None or hi is None:
            raise MathError("حدود x يجب أن تكون أرقامًا صالحة")
        if lo >= hi:
            raise MathError("يجب أن تكون بداية x أصغر من نهايتها")
        if hi - lo > 1e7:
            raise MathError("نطاق x كبير جدًا")
        return lo, hi

    def plot_graph(self):
        self._plot_ready = True
        text = self.graph_entry.get().strip() or "sin(x)"
        if not self.graph_entry.get().strip():
            self.graph_entry.insert(0, text)
        try:
            lo, hi = self._read_x_range()
            funcs = []
            for part in re.split(r"[;؛]", text):
                part = part.strip()
                if not part:
                    continue
                part = re.sub(r"^(?:y|f\s*\(\s*x\s*\))\s*=", "", part, flags=re.I).strip()
                translated = part.translate(_TRANSLATE)
                if "=" in translated:
                    left, right = translated.split("=", 1)
                    for side in (left, right):
                        funcs.append((side.strip(), parse_expression(side, self.angle_mode)))
                else:
                    funcs.append((part, parse_expression(part, self.angle_mode)))
            if not funcs:
                raise MathError("اكتب دالة للرسم")
            if len(funcs) > 6:
                raise MathError("الحد الأقصى 6 منحنيات")
            self.plot_funcs = [(label, make_curve(expr)) for label, expr in funcs]
        except MathError as exc:
            self.graph_status.configure(text=f"⚠ {exc}", text_color=ERR_COLOR)
            return
        self.view[0], self.view[1] = lo, hi
        self.auto_y = True
        self.render_plot()
        self.graph_status.configure(text=f"تم رسم {len(self.plot_funcs)} منحنى · عجلة الفأرة للتكبير · اسحب للتحريك",
                                    text_color=MUTED)
        self.add_history(f"رسم: {text}", f"x ∈ [{format_number(lo)}, {format_number(hi)}]")

    def render_plot(self):
        self._plot_job = None
        ax = self.ax
        ax.clear()
        c = self.graph_colors()
        xmin, xmax = self.view[0], self.view[1]
        xs = np.linspace(xmin, xmax, 1400)
        curves = []
        for idx, (label, fn) in enumerate(self.plot_funcs):
            ys = break_discontinuities(fn(xs))
            curves.append((label, ys))
        if self.auto_y:
            allv = np.concatenate([y[np.isfinite(y)] for _, y in curves]) if curves else np.array([])
            if allv.size:
                lo, hi = np.percentile(allv, [1.5, 98.5])
                if hi - lo < 1e-9:
                    lo, hi = lo - 1, hi + 1
                pad = 0.12 * (hi - lo)
                self.view[2], self.view[3] = float(lo - pad), float(hi + pad)
            else:
                self.view[2], self.view[3] = -6.0, 6.0
        for idx, (label, ys) in enumerate(curves):
            ax.plot(xs, ys, color=c["curves"][idx % len(c["curves"])], linewidth=2.0 * clamp(self._plot_scale, 0.8, 1.3),
                    label=label)
        ax.set_xlim(self.view[0], self.view[1])
        ax.set_ylim(self.view[2], self.view[3])
        self.style_axes()
        if len(curves) > 1:
            leg = ax.legend(loc="upper right", fontsize=9 * self._plot_scale, facecolor=c["ax"], edgecolor=c["axis"])
            for t in leg.get_texts():
                t.set_color(c["text"])
        self.canvas.draw_idle()

    def reset_view(self):
        try:
            lo, hi = self._read_x_range()
        except MathError as exc:
            self.graph_status.configure(text=f"⚠ {exc}", text_color=ERR_COLOR)
            return
        self.view[0], self.view[1] = lo, hi
        self.auto_y = True
        self.render_plot()

    def save_plot_image(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".png", title="حفظ الرسم",
                                            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")])
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=200, facecolor=self.fig.get_facecolor())
            self.flash_status("تم حفظ الصورة ✓")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("تعذر الحفظ", str(exc), parent=self)

    def on_plot_scroll(self, event):
        if event.inaxes is not self.ax or event.xdata is None:
            return
        factor = 0.8 if event.button == "up" else 1.25
        cx, cy = event.xdata, event.ydata
        v = self.view
        v[0], v[1] = cx + (v[0] - cx) * factor, cx + (v[1] - cx) * factor
        v[2], v[3] = cy + (v[2] - cy) * factor, cy + (v[3] - cy) * factor
        self.auto_y = False
        self.render_plot()

    def on_plot_press(self, event):
        if event.inaxes is not self.ax or event.button != 1:
            return
        if getattr(event, "dblclick", False):
            self.reset_view()
            return
        self._pan = (event.x, event.y, list(self.view))

    def on_plot_release(self, event):
        self._pan = None

    def on_plot_motion(self, event):
        if self._pan is not None and event.x is not None:
            sx, sy, v0 = self._pan
            bbox = self.ax.bbox
            dx = (event.x - sx) / max(bbox.width, 1) * (v0[1] - v0[0])
            dy = (event.y - sy) / max(bbox.height, 1) * (v0[3] - v0[2])
            self.view = [v0[0] - dx, v0[1] - dx, v0[2] - dy, v0[3] - dy]
            self.auto_y = False
            if self._plot_job is None:
                self._plot_job = self.after(16, self.render_plot)
        if event.inaxes is self.ax and event.xdata is not None:
            self.coord_label.configure(text=f"x = {_fmt_real(event.xdata)}   y = {_fmt_real(event.ydata)}")
        else:
            self.coord_label.configure(text="")

    def switch_and_plot(self):
        text = self.get_input()
        if text:
            self.graph_entry.delete(0, "end")
            self.graph_entry.insert(0, text)
        self.tabview.set(TAB_GRAPH)
        self.plot_graph()

    def on_tab_change(self):
        tab = self.tabview.get()
        if tab == TAB_GRAPH:
            if not self._plot_ready:
                self.after(30, self.plot_graph)
            else:
                self.after(30, self.render_plot)
        elif tab == TAB_CALC:
            self.display.focus_set()

    # ==================================================================
    # العملات
    # ==================================================================
    def load_rates(self):
        self.rates = {c: v[1] for c, v in CURRENCIES.items()}
        self.rate_locked: set[str] = set()
        self.rate_date = ""
        self.rate_source = DEFAULT_SOURCE_LABEL
        data = load_json(RATES_FILE)
        legacy = False
        if data is None:
            data = load_json(LEGACY_RATES_FILE)
            legacy = data is not None
        if not isinstance(data, dict):
            return
        try:
            if data.get("version") == 3 and isinstance(data.get("per_usd"), dict):
                for code, v in data["per_usd"].items():
                    if code in self.rates and isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
                        self.rates[code] = float(v)
                self.rate_locked = {c for c in data.get("locked", []) if c in self.rates}
                self.rate_date = str(data.get("date", ""))
                self.rate_source = str(data.get("source", DEFAULT_SOURCE_LABEL))
            else:   # الصيغة القديمة: قيمة الوحدة بالدولار
                old = data.get("rates") if isinstance(data.get("rates"), dict) else data
                for code, v in old.items():
                    if code in self.rates and isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
                        self.rates[code] = 1.0 / float(v)
                self.rates["USD"] = 1.0
                self.rate_date = str(data.get("date", "")) if isinstance(data.get("date"), str) else ""
                self.rate_source = "أسعار محفوظة (نسخة سابقة)"
                if legacy:
                    self.save_rates()
        except Exception:
            self.rates = {c: v[1] for c, v in CURRENCIES.items()}

    def save_rates(self) -> bool:
        ok = save_json(RATES_FILE, {"version": 3, "per_usd": self.rates, "locked": sorted(self.rate_locked),
                                    "date": self.rate_date, "source": self.rate_source})
        if not ok:
            messagebox.showerror("تعذر الحفظ", "لم يتم حفظ أسعار الصرف على هذا الجهاز.", parent=self)
        return ok

    def update_rates_status(self):
        if not self.rate_date:
            text, color = "⚠ أسعار افتراضية تقريبية — اضغط «تحديث الأسعار»", ("#b45309", "#fbbf24")
        else:
            text, color = f"المصدر: {self.rate_source} · التاريخ: {self.rate_date}", MUTED
        self.rates_status.configure(text=text, text_color=color)

    def auto_refresh_rates_if_stale(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.settings.get("auto_update", True) and self.rate_date != today and not self.rate_refreshing:
            self.refresh_rates_async(silent=True)

    def refresh_rates_async(self, silent=False):
        if self.rate_refreshing:
            return
        self.rate_refreshing = True
        self.refresh_btn.configure(state="disabled", text="جارٍ التحديث…")
        codes = list(CURRENCIES)

        def worker():
            try:
                self.rate_queue.put((True, fetch_rates_online(codes), silent))
            except Exception as exc:  # noqa: BLE001
                self.rate_queue.put((False, str(exc), silent))

        threading.Thread(target=worker, daemon=True, name="rates").start()
        self.after(200, self.poll_rates)

    def poll_rates(self):
        if self._closing:
            return
        try:
            ok, result, silent = self.rate_queue.get_nowait()
        except queue.Empty:
            if self.rate_refreshing:
                self.after(200, self.poll_rates)
            return
        self.rate_refreshing = False
        self.refresh_btn.configure(state="normal", text="🌐 تحديث الأسعار")
        if not ok:
            if not silent:
                self.rates_status.configure(text=f"⚠ {result}", text_color=ERR_COLOR)
            return
        new_rates, date, sources, missing = result
        old = (dict(self.rates), self.rate_date, self.rate_source)
        for code, v in new_rates.items():
            if code in self.rates and code not in self.rate_locked:
                self.rates[code] = v
        self.rate_date, self.rate_source = date, " + ".join(sources)
        if not self.save_rates():
            self.rates, self.rate_date, self.rate_source = old
            return
        self.update_rates_status()
        self.update_currency_result()
        if missing and not silent:
            self.rates_status.configure(text=f"تم التحديث ({date}). لم تتوفر: {', '.join(missing)}", text_color=MUTED)
        if not silent:
            self.flash_status("تم تحديث أسعار العملات ✓")

    @staticmethod
    def _code(label: str) -> str:
        return label.split()[0]

    def update_currency_result(self, log=False):
        f, t = self._code(self.from_currency.get()), self._code(self.to_currency.get())
        val = parse_amount(self.cur_amount.get())
        rate = self.rates[t] / self.rates[f]
        self.cur_rate_label.configure(
            text=f"1 {f} = {format_money(rate)} {t}\n{CURRENCIES[f][0]} ← {CURRENCIES[t][0]}")
        if val is None:
            self.cur_result.configure(text="—" if not self.cur_amount.get().strip() else "؟", text_color=MUTED)
            self._last_currency_value = ""
            return
        result = val * rate
        self.cur_result.configure(text=f"{format_money(result)} {t}", text_color=OK_COLOR)
        self._last_currency_value = _fmt_real(result)
        if log:
            self.add_history(f"{format_money(val)} {f}", f"{format_money(result)} {t}")

    def swap_currency(self):
        f, t = self.from_currency.get(), self.to_currency.get()
        self.from_currency.set(t)
        self.to_currency.set(f)
        self.update_currency_result()

    def edit_rates(self):
        win = ctk.CTkToplevel(self)
        win.title("تعديل أسعار الصرف")
        win.transient(self)
        ctk.CTkLabel(win, text="اكتب عدد وحدات كل عملة مقابل 1 دولار أمريكي (مثال: 1 USD = 3.75 SAR).\n"
                               "فعّل «تثبيت» ليحتفظ البرنامج بالسعر ولا يغيّره التحديث التلقائي.",
                     font=self.fonts["small"], wraplength=440, justify="right").pack(padx=14, pady=(12, 6))
        scroll = ctk.CTkScrollableFrame(win, height=310, width=440)
        scroll.pack(padx=12, pady=4, fill="both", expand=True)
        scroll.grid_columnconfigure(1, weight=1)
        entries, locks = {}, {}
        for r, (code, (name, _)) in enumerate(CURRENCIES.items()):
            ctk.CTkLabel(scroll, text=f"{code} — {name}", font=self.fonts["small"], anchor="e").grid(row=r, column=0, padx=6, pady=5, sticky="e")
            e = ctk.CTkEntry(scroll, width=130, font=self.fonts["body"], justify="center")
            e.insert(0, "1" if code == "USD" else repr(round(self.rates[code], 6)))
            if code == "USD":
                e.configure(state="disabled")
            e.grid(row=r, column=1, padx=6, pady=5)
            entries[code] = e
            self.add_help(e, f"سعر {code}", f"عدد وحدات {code} مقابل 1 دولار. يجب أن يكون أكبر من الصفر.")
            if code != "USD":
                sv = ctk.BooleanVar(value=code in self.rate_locked)
                sw = ctk.CTkSwitch(scroll, text="تثبيت", variable=sv, font=self.fonts["small"], width=60)
                sw.grid(row=r, column=2, padx=6, pady=5)
                locks[code] = sv
                self.add_help(sw, "تثبيت السعر", "عند التفعيل لا يغيّر التحديث التلقائي هذا السعر.")

        def save():
            new = {"USD": 1.0}
            for code, e in entries.items():
                if code == "USD":
                    continue
                val = parse_amount(e.get())
                if val is None or val <= 0:
                    messagebox.showerror("قيمة غير صالحة", f"أدخل رقمًا موجبًا صالحًا للعملة {code}.", parent=win)
                    return
                new[code] = val
            old = (dict(self.rates), set(self.rate_locked), self.rate_date, self.rate_source)
            changed = {c for c in new if abs(new[c] - self.rates[c]) > 1e-12}
            self.rates = new
            self.rate_locked = {c for c, v in locks.items() if v.get()} | changed
            if changed:
                self.rate_source, self.rate_date = "تعديل يدوي", datetime.now().strftime("%Y-%m-%d")
            if not self.save_rates():
                self.rates, self.rate_locked, self.rate_date, self.rate_source = old
                return
            self.update_rates_status()
            self.update_currency_result()
            win.destroy()

        def reset():
            for code, e in entries.items():
                if code != "USD":
                    e.delete(0, "end")
                    e.insert(0, repr(CURRENCIES[code][1]))
                    locks[code].set(False)

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=(6, 12))
        for text, cmd, color in (("💾 حفظ", save, "#27ae60"), ("↺ الافتراضي", reset, "#6b7280"), ("إلغاء", win.destroy, "#c0392b")):
            b = ctk.CTkButton(row, text=text, command=cmd, fg_color=color, width=110, font=self.fonts["small_btn"])
            b.pack(side="left", padx=5)
            self.add_help(b, text.split()[-1], {"حفظ": "يتحقق من القيم ويحفظها على هذا الجهاز.",
                                                  "الافتراضي": "يعيد الأسعار الافتراضية التقريبية (لا يحفظ حتى تضغط حفظ).",
                                                  "إلغاء": "يغلق النافذة دون حفظ."}[text.split()[-1]])
        self._center_dialog(win)

    def _center_dialog(self, win):
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 3)
        try:
            win.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        win.after(120, lambda: (win.lift(), win.focus_force()))
        win.after(160, lambda: self._safe_grab(win))

    @staticmethod
    def _safe_grab(win):
        try:
            win.grab_set()
        except tk.TclError:
            pass

    # ==================================================================
    # الوحدات
    # ==================================================================
    def on_category_change(self, cat):
        units = UNIT_CATEGORIES[cat]
        labels = list(units)
        self.from_unit_menu.configure(values=labels)
        self.to_unit_menu.configure(values=labels)
        self.from_unit.set(labels[0])
        self.to_unit.set(labels[1] if len(labels) > 1 else labels[0])
        if cat == "الحرارة":
            self.from_unit.set(labels[0])
            self.to_unit.set(labels[1])
        self.update_unit_result()

    def update_unit_result(self, log=False):
        cat = self.unit_category.get()
        f, t = self.from_unit.get().split(" — ")[0], self.to_unit.get().split(" — ")[0]
        val = parse_amount(self.unit_amount.get())
        if val is None:
            self.unit_result.configure(text="—" if not self.unit_amount.get().strip() else "؟", text_color=MUTED)
            self._last_unit_value = ""
            return
        try:
            result = convert_unit(val, cat, f, t)
        except MathError as exc:
            self.unit_result.configure(text=f"⚠ {exc}", text_color=ERR_COLOR)
            self._last_unit_value = ""
            return
        self.unit_result.configure(text=f"{format_money(result)} {t}", text_color=OK_COLOR)
        names = UNIT_CATEGORIES[cat]
        self.unit_caption.configure(text=f"{names[f][1]} ← {names[t][1]}")
        self._last_unit_value = _fmt_real(result)
        if log:
            self.add_history(f"{format_money(val)} {f}", f"{format_money(result)} {t}")

    def swap_units(self):
        f, t = self.from_unit.get(), self.to_unit.get()
        self.from_unit.set(t)
        self.to_unit.set(f)
        self.update_unit_result()

    # ==================================================================
    # الاختصارات
    # ==================================================================
    def bind_shortcuts(self):
        self.bind("<Return>", self.on_return, add="+")
        self.bind("<KP_Enter>", self.on_return, add="+")
        self.bind("<Escape>", self.on_escape, add="+")
        self.bind("<Key>", self.on_key, add="+")
        inner = self.display._entry
        inner.bind("<KeyPress>", self.on_display_key, add="+")
        inner.bind("<Control-c>", self.on_display_copy, add="+")
        inner.bind("<Control-C>", self.on_display_copy, add="+")

    def on_return(self, event=None):
        w = self.focus_get()
        handler = self._return_handlers.get(w)
        if handler:
            handler()
        else:
            self.calculate()
        return "break"

    def on_escape(self, event=None):
        self.hide_help()
        w = self.focus_get()
        if w is None or w is self.display._entry or not isinstance(w, (tk.Entry, tk.Text)):
            self.clear()

    def on_key(self, event):
        w = self.focus_get()
        if isinstance(w, (tk.Entry, tk.Text)) or self.tabview.get() != TAB_CALC:
            return
        if event.keysym == "BackSpace":
            self.backspace()
            return "break"
        ch = event.char
        if ch and ch in ALLOWED_TYPING:
            self.insert_text(ch)
            return "break"

    def on_display_key(self, event):
        ch = event.char
        if self.result_shown and ch and ch.isprintable():
            if not (self.result_chainable and ch in "+-*/^%"):
                self.display.delete(0, "end")
            else:
                self.display.icursor("end")
            self.result_shown = False
        elif event.keysym in ("BackSpace", "Delete") and self.result_shown:
            if self.result_chainable:
                self.result_shown = False
            else:
                self.clear()
                return "break"

    def on_display_copy(self, event):
        try:
            if self.display._entry.selection_present():
                return None
        except tk.TclError:
            pass
        self.copy_text(self.display_var.get())
        return "break"

    # ==================================================================
    # الثيم والنوافذ
    # ==================================================================
    def toggle_theme(self):
        new = "light" if ctk.get_appearance_mode() == "Dark" else "dark"
        ctk.set_appearance_mode(new)
        self.settings["theme"] = new
        save_json(SETTINGS_FILE, self.settings)
        self.after(50, self.render_plot)

    def _make_dialog(self, title):
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.transient(self)
        return win

    def show_about(self):
        win = self._make_dialog(f"حول {APP_NAME}")
        ctk.CTkLabel(win, text=f"{APP_NAME} {APP_VERSION}", font=ctk.CTkFont(family=self.font_family, size=24, weight="bold")).pack(padx=30, pady=(18, 4))
        ctk.CTkLabel(win, text="آلة حاسبة علمية وهندسية متكاملة", font=self.fonts["body"]).pack(pady=2)
        features = ("✨ المميزات:\n"
                    "• حسابات علمية متقدمة وكتابة طبيعية (2x ، 3(4+1) ، 50%)\n"
                    "• حل المعادلات والتفاضل والتكامل الرمزي\n"
                    "• رسم بياني تفاعلي (تكبير وتحريك وحفظ كصورة)\n"
                    "• محول عملات بتحديث تلقائي ومحول وحدات متعدد\n"
                    "• شرح لكل زر بالضغط على الزر الأيمن للفأرة")
        ctk.CTkLabel(win, text=features, justify="right", anchor="e", wraplength=420, font=self.fonts["small"]).pack(padx=24, pady=12)
        ctk.CTkLabel(win, text=f"المطور: {DEVELOPER_NAME}", font=self.fonts["bold"]).pack(pady=4)
        ctk.CTkButton(win, text=f"تواصل عبر واتساب: {WHATSAPP_NUMBER} 💬", fg_color="#27ae60", hover_color="#2ecc71",
                      command=lambda: webbrowser.open(WHATSAPP_URL), font=self.fonts["btn"]).pack(padx=20, pady=10)
        ctk.CTkLabel(win, text=COPYRIGHT_TEXT, font=self.fonts["small"], text_color=MUTED).pack(pady=(4, 14))
        self._center_dialog(win)

    def show_guide(self):
        win = self._make_dialog("دليل الاستخدام")
        box = ctk.CTkTextbox(win, width=520, height=440, font=self.fonts["body"], wrap="word")
        box.pack(padx=12, pady=12, fill="both", expand=True)
        box.tag_config("rtl", justify="right")
        guide = (
            "🧮 الحاسبة\n"
            "• اكتب بالأزرار أو بلوحة المفاتيح. الضرب الضمني مدعوم: 2x ، 3(4+1) ، 2sin(30).\n"
            "• % تعني ÷100: 200 × 10% = 20.\n"
            "• الدوال: sin cos tan asin acos atan sinh cosh tanh sqrt cbrt abs sign exp ln log fact floor ceil mod(a,b).\n"
            "• log لوغاريتم أساس 10 و ln لوغاريتم طبيعي.\n"
            "• الأعداد العربية ٠١٢٣ تُقبل تلقائيًا.\n\n"
            "📐 المعادلات والتفاضل والتكامل\n"
            "• معادلة: اكتب x^2 - 4 = 0 ثم اضغط =.\n"
            "• d/dx للمشتقة و ∫dx للتكامل غير المحدد، ويمكن تسلسلهما على النتيجة.\n\n"
            "📈 الرسم البياني\n"
            "• افصل بين الدوال بـ ; لرسم أكثر من منحنى (حتى 6).\n"
            "• عجلة الفأرة: تكبير/تصغير، السحب: تحريك، نقر مزدوج: إعادة الضبط.\n\n"
            "💱 المحولات\n"
            "• التحويل فوري أثناء الكتابة؛ Enter يسجله في السجل.\n"
            "• «تحديث الأسعار» يجلب أسعارًا مرجعية من الإنترنت. يمكنك تعديل أي سعر يدويًا وتثبيته (مفيد للريال اليمني).\n\n"
            "⌨️ الاختصارات\n"
            "• Enter = احسب   • Esc = مسح   • Backspace = حذف   • Ctrl+C = نسخ الشاشة   • Ctrl+V = لصق\n"
            "• بزر الفأرة الأيمن على أي عنصر تظهر رسالة شرح صغيرة."
        )
        box.insert("1.0", guide, "rtl")
        box.configure(state="disabled")
        self._center_dialog(win)


def main():
    app = CalculatorProApp()
    app.mainloop()


if __name__ == "__main__":
    main()

