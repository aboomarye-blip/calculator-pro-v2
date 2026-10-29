import ast
import json
import math
import os
import queue
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox
import customtkinter as ctk
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from sympy import symbols, Eq, solve, diff, integrate, lambdify, pi, E, sin, cos, tan, log, sqrt, sympify

APP_VERSION = "V2.2"
UI_FONT = "Tahoma"
FONT_SMALL = (UI_FONT, 14)
FONT_BODY = (UI_FONT, 15)
FONT_BODY_BOLD = (UI_FONT, 15, "bold")
FONT_BUTTON = (UI_FONT, 15, "bold")
FONT_SECTION = (UI_FONT, 18, "bold")

# إعداد المظهر العام
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_DATA_DIR = Path(os.getenv("APPDATA", Path.home())) / "CalculatorPro"
RATES_FILE = APP_DATA_DIR / "exchange_rates.json"
LEGACY_RATES_FILE = Path.cwd() / "exchange_rates.json"
RATES_API_URL = "https://api.frankfurter.dev/v2/rates"

SAFE_FUNCTIONS = {"sin": sin, "cos": cos, "tan": tan, "log": log, "sqrt": sqrt}


def parse_expression(source, angle_mode="Radians"):
    """Parse a small, explicitly allowed math grammar without evaluating Python code."""
    if len(source) > 256:
        raise ValueError("المعادلة طويلة جدًا")
    tree = ast.parse(source, mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 80:
        raise ValueError("المعادلة معقدة جدًا")
    x = symbols("x")
    names = {"x": x, "pi": pi, "E": E}

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(node.value):
                raise ValueError("الأعداد اللانهائية غير مسموحة")
            return node.value
        if isinstance(node, ast.Name):
            if node.id in names:
                return names[node.id]
            raise ValueError(f"الرمز غير مسموح: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in {
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod
        }:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and not getattr(right, "free_symbols", set()):
                try:
                    if abs(right) > 100:
                        raise ValueError("الأس أكبر من الحد المسموح")
                except TypeError:
                    pass
            return {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                    ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
                    ast.Pow: lambda: left ** right, ast.Mod: lambda: left % right}[type(node.op)]()
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCTIONS:
            if node.keywords or len(node.args) != 1:
                raise ValueError("تقبل الدالة معاملًا واحدًا فقط")
            argument = visit(node.args[0])
            if angle_mode == "Degrees" and node.func.id in {"sin", "cos", "tan"}:
                argument = argument * pi / 180
            return SAFE_FUNCTIONS[node.func.id](argument)
        raise ValueError("صيغة رياضية غير مدعومة")

    # Normalize Python numeric literals to SymPy values before downstream operations.
    return sympify(visit(tree))

DEFAULT_RATES = {
    "USD": 1.0,
    "SAR": 0.266667,   # 1 SAR ≈ 0.2667 USD (1 USD = 3.75 SAR)
    "YER": 0.00186567, # 1 YER ≈ 0.00186 USD (1 USD ≈ 536 YER)
    "QAR": 0.274725,   # 1 QAR ≈ 0.2747 USD (1 USD = 3.64 QAR)
    "EUR": 1.08,
    "GBP": 1.27
}

LENGTH_UNITS = {
    "km": 1000.0,
    "m": 1.0,
    "cm": 0.01,
    "mm": 0.001,
    "inch": 0.0254,
    "ft": 0.3048
}

WEIGHT_UNITS = {
    "kg": 1.0,
    "g": 0.001,
    "mg": 0.000001,
    "lb": 0.45359237,
    "oz": 0.0283495
}

TEMP_UNITS = ["C", "F", "K"]


class CalculatorProApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Calculator Pro {APP_VERSION} - النسخة الاحترافية المطورة")
        self.geometry("1100x720")
        self.minsize(800, 600)

        # المتغيرات الأساسية
        self.expression = ""
        self.memory = 0.0
        self.result_shown = False
        self.angle_mode = "Radians"
        self.rate_date = "غير معروف"
        self.rate_source = "أسعار افتراضية تقريبية"
        self.rate_update_queue = queue.Queue()
        self.rate_refreshing = False
        self.rates = self.load_rates()

        self.display_var = ctk.StringVar(value="")

        # بناء الواجهة الرسومية
        self.setup_ui()
        self.attach_context_help(self)
        self.bind_shortcuts()
        self._resize_job = None
        self._compact_layout = False
        self._widget_scale = 1.0
        self.help_popup = None
        self.bind("<Configure>", self.schedule_responsive_layout, add="+")
        self.bind_all("<Button-1>", self.dismiss_help_popup, add="+")
        self.after(500, self.poll_rate_update)

    # ==========================================
    # إدارة ملف أسعار الصرف (JSON Persistence)
    # ==========================================
    def load_rates(self):
        path = RATES_FILE if RATES_FILE.exists() else LEGACY_RATES_FILE
        try:
            with path.open("r", encoding="utf-8") as f:
                saved = json.load(f)
            if not isinstance(saved, dict):
                raise ValueError("ملف أسعار الصرف ليس كائنًا صالحًا")
            if isinstance(saved.get("rates"), dict):
                self.rate_date = str(saved.get("date", "غير معروف"))
                self.rate_source = str(saved.get("source", "محلي"))
                saved = saved["rates"]
            elif path == RATES_FILE:
                # Backward compatibility with the V2.2 flat JSON format.
                self.rate_source = "أسعار محلية محفوظة"
            rates = DEFAULT_RATES.copy()
            for currency, value in saved.items():
                if currency in rates and isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                    rates[currency] = float(value)
            if path == LEGACY_RATES_FILE and path.exists():
                self.rates = rates
                self.save_rates_to_file()
            return rates
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return DEFAULT_RATES.copy()

    def save_rates_to_file(self):
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = RATES_FILE.with_suffix(".json.tmp")
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump({
                    "version": 2,
                    "rates": self.rates,
                    "date": self.rate_date,
                    "source": self.rate_source,
                }, f, indent=4, ensure_ascii=False)
            os.replace(temp_file, RATES_FILE)
            return True
        except OSError as e:
            messagebox.showerror("تعذر الحفظ", f"لم يتم حفظ أسعار الصرف.\n{e}", parent=self)
            return False

    def fetch_exchange_rates(self, currencies=None):
        currencies = tuple(currencies or (code for code in self.rates if code != "USD"))
        query = urllib.parse.urlencode({"base": "USD", "quotes": ",".join(currencies)})
        request = urllib.request.Request(
            f"{RATES_API_URL}?{query}",
            headers={"User-Agent": f"CalculatorPro/{APP_VERSION}"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            records = json.loads(response.read().decode("utf-8"))
        if not isinstance(records, list):
            raise ValueError("استجابة أسعار الصرف غير صالحة")

        rates = {"USD": 1.0}
        dates = []
        for record in records:
            code = record.get("quote")
            rate = record.get("rate")
            date = record.get("date")
            if code in currencies and isinstance(rate, (int, float)) and math.isfinite(rate) and rate > 0:
                rates[code] = 1.0 / float(rate)
                if isinstance(date, str):
                    dates.append(date)
        missing = sorted(set(currencies) - set(rates))
        if missing:
            raise ValueError("المصدر لا يوفر العملات: " + ", ".join(missing))
        date_label = min(dates) if dates else "غير معروف"
        if dates and min(dates) != max(dates):
            date_label = f"{min(dates)} إلى {max(dates)}"
        return rates, date_label

    def refresh_rates_async(self):
        if self.rate_refreshing:
            return
        self.rate_refreshing = True
        self.refresh_rates_button.configure(state="disabled", text="جارٍ التحديث…")
        self.edit_rates_button.configure(state="disabled")
        currencies = tuple(code for code in self.rates if code != "USD")

        def worker():
            try:
                self.rate_update_queue.put((True, self.fetch_exchange_rates(currencies)))
            except Exception as exc:
                self.rate_update_queue.put((False, str(exc)))

        threading.Thread(target=worker, daemon=True, name="exchange-rate-refresh").start()
        self.after(150, self.poll_rate_update)

    def poll_rate_update(self):
        try:
            succeeded, result = self.rate_update_queue.get_nowait()
        except queue.Empty:
            if self.rate_refreshing:
                self.after(150, self.poll_rate_update)
            return

        self.rate_refreshing = False
        self.refresh_rates_button.configure(state="normal", text="تحديث أسعار العملات 🌐")
        self.edit_rates_button.configure(state="normal")
        if not succeeded:
            messagebox.showwarning(
                "تعذر تحديث الأسعار", f"لم تتغير الأسعار المحفوظة.\n{result}", parent=self
            )
            return

        new_rates, date_label = result
        old_rates = self.rates.copy()
        old_date, old_source = self.rate_date, self.rate_source
        self.rates = new_rates
        self.rate_date = date_label
        self.rate_source = "Frankfurter — أسعار مرجعية يومية"
        if not self.save_rates_to_file():
            self.rates, self.rate_date, self.rate_source = old_rates, old_date, old_source
            return
        self.update_rates_box()
        self.add_history(f"تم تحديث أسعار العملات ({date_label})")
        messagebox.showinfo("اكتمل التحديث", f"تم تحديث أسعار العملات.\nتواريخ البيانات: {date_label}", parent=self)

    def schedule_responsive_layout(self, event):
        if event.widget is not self:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self.update_responsive_layout)

    def update_responsive_layout(self):
        self._resize_job = None
        width = self.winfo_width()
        height = self.winfo_height()
        target_scale = max(0.78, min(1.15, min(width / 1100, height / 720)))
        if abs(target_scale - self._widget_scale) >= 0.04:
            self._widget_scale = target_scale
            ctk.set_widget_scaling(target_scale)
        # Hide the history pane on narrow windows so the calculator keeps usable keys.
        if not self._compact_layout and width < 1000:
            self.side_frame.grid_remove()
            self.tabview.grid_configure(columnspan=2, padx=(15, 15))
            self._compact_layout = True
        elif self._compact_layout and width >= 1120:
            self.tabview.grid_configure(columnspan=1, padx=(15, 5))
            self.side_frame.grid(row=1, column=1, padx=(5, 15), pady=(5, 15), sticky="nsew")
            self._compact_layout = False

    def bind_context_help(self, widget, text):
        widget.bind("<Button-3>", lambda event: self.show_context_help(event, text), add="+")

    def attach_context_help(self, parent):
        for widget in parent.winfo_children():
            help_text = None
            if isinstance(widget, ctk.CTkButton):
                help_text = self.button_help_text(widget.cget("text"))
            elif isinstance(widget, ctk.CTkOptionMenu):
                if widget is getattr(self, "angle_mode_menu", None):
                    help_text = "اختر درجات أو راديان للدوال المثلثية. يطبق الاختيار على الحساب والتفاضل والرسم."
                elif widget is getattr(self, "from_curr_menu", None):
                    help_text = "اختر العملة التي يبدأ منها التحويل."
                elif widget is getattr(self, "to_curr_menu", None):
                    help_text = "اختر العملة التي تريد التحويل إليها."
                elif widget is getattr(self, "from_unit_menu", None):
                    help_text = "اختر وحدة القيمة الحالية."
                elif widget is getattr(self, "to_unit_menu", None):
                    help_text = "اختر الوحدة التي تريد التحويل إليها."
                elif widget is getattr(self, "category_menu", None):
                    help_text = "اختر فئة الوحدات: طول أو وزن أو درجة حرارة."
                else:
                    help_text = "اختر قيمة من القائمة المنسدلة."
            elif isinstance(widget, ctk.CTkEntry):
                if widget is getattr(self, "display", None):
                    help_text = "تعرض هذه الشاشة التعبير والنتيجة. استخدم الأزرار أو لوحة المفاتيح لإدخال الحساب."
                elif widget is getattr(self, "x_min_entry", None):
                    help_text = "أدخل أصغر قيمة x لنطاق الرسم. يجب أن تكون أقل من الحد الأعلى."
                elif widget is getattr(self, "x_max_entry", None):
                    help_text = "أدخل أكبر قيمة x لنطاق الرسم. يجب أن تكون أكبر من الحد الأدنى."
            if help_text:
                self.bind_context_help(widget, help_text)
            self.attach_context_help(widget)

    def show_context_help(self, event, text):
        self.dismiss_help_popup()
        popup = ctk.CTkToplevel(self)
        self.help_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(fg_color=("#f6f6f6", "#242424"))
        label = ctk.CTkLabel(
            popup, text=text, font=FONT_SMALL, justify="right", anchor="e",
            wraplength=300
        )
        label.pack(fill="both", expand=True, padx=12, pady=9)
        popup.update_idletasks()
        x, y = self.winfo_pointerxy()
        width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
        x = min(x + 12, popup.winfo_screenwidth() - width - 8)
        y = min(y + 12, popup.winfo_screenheight() - height - 8)
        popup.geometry(f"+{max(8, x)}+{max(8, y)}")
        popup.after(4500, self.dismiss_help_popup)
        return "break"

    def dismiss_help_popup(self, event=None):
        if self.help_popup is not None:
            try:
                self.help_popup.destroy()
            except Exception:
                pass
            self.help_popup = None

    # ==========================================
    # بناء الواجهة الرسومية (UI Setup)
    # ==========================================
    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. الشريط العلوي وشاشة العرض
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.grid(row=0, column=0, columnspan=2, padx=15, pady=(15, 5), sticky="nsew")
        top_frame.grid_columnconfigure(0, weight=1)

        self.display = ctk.CTkEntry(
            top_frame,
            textvariable=self.display_var,
            font=(UI_FONT, 34, "bold"),
            justify="right",
            height=75,
            state="readonly"  # منع الكتابة المزدوجة المباشرة
        )
        self.display.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        about_btn = ctk.CTkButton(
            top_frame, text="حول البرنامج ℹ️", width=120, height=75,
            font=FONT_BUTTON, command=self.show_about
        )
        about_btn.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(
            top_frame, text="اضغط بزر الفأرة الأيمن على أي زر لمعرفة وظيفته",
            font=FONT_SMALL, anchor="e"
        ).grid(row=1, column=0, columnspan=2, padx=5, pady=(2, 0), sticky="e")

        # 2. نظام التبويبات الرئيسي
        self.tabview = ctk.CTkTabview(self)
        self.tabview._segmented_button.configure(font=FONT_BUTTON)
        self.tabview.grid(row=1, column=0, padx=(15, 5), pady=(5, 15), sticky="nsew")

        self.tab_calc = self.tabview.add("الحاسبة العلمية والتفاضل")
        self.tab_graph = self.tabview.add("الرسم البياني للدوال")
        self.tab_conv = self.tabview.add("محول العملات والوحدات")

        self.setup_calculator_tab()
        self.setup_graph_tab()
        self.setup_converter_tab()

        # 3. اللوحة الجانبية (السجل والذاكرة)
        self.side_frame = ctk.CTkFrame(self)
        self.side_frame.grid(row=1, column=1, padx=(5, 15), pady=(5, 15), sticky="nsew")
        self.side_frame.grid_rowconfigure(1, weight=1)
        self.side_frame.grid_columnconfigure(0, weight=1)

        hist_label = ctk.CTkLabel(self.side_frame, text="سجل العمليات (History)", font=FONT_SECTION)
        hist_label.grid(row=0, column=0, pady=(10, 5))

        self.history_box = ctk.CTkTextbox(self.side_frame, width=250, font=FONT_SMALL)
        self.history_box.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")

        self.mem_label = ctk.CTkLabel(
            self.side_frame, text=f"الذاكرة (Memory): {self.format_number(self.memory)}", font=FONT_SMALL
        )
        self.mem_label.grid(row=2, column=0, pady=5)

        clear_hist_btn = ctk.CTkButton(
            self.side_frame, text="مسح السجل 🗑️", fg_color="#c0392b", hover_color="#e74c3c",
            command=self.clear_history, font=FONT_BUTTON
        )
        clear_hist_btn.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

    # ------------------------------------------
    # تبويب 1: الحاسبة العلمية
    # ------------------------------------------
    def setup_calculator_tab(self):
        for r in range(8):
            self.tab_calc.grid_rowconfigure(r, weight=1)
        for c in range(6):
            self.tab_calc.grid_columnconfigure(c, weight=1)

        # صف الذاكرة والمسح
        self.create_btn(self.tab_calc, "MC", self.memory_clear, 0, 0, fg="#34495e")
        self.create_btn(self.tab_calc, "MR", self.memory_recall, 0, 1, fg="#34495e")
        self.create_btn(self.tab_calc, "M+", self.memory_add, 0, 2, fg="#34495e")
        self.create_btn(self.tab_calc, "M-", self.memory_sub, 0, 3, fg="#34495e")
        self.create_btn(self.tab_calc, "C (مسح)", self.clear, 0, 4, fg="#c0392b")
        self.create_btn(self.tab_calc, "⌫", self.backspace, 0, 5, fg="#d35400")

        # صف الدوال العلمية الأول
        self.create_btn(self.tab_calc, "sin", lambda: self.press("sin("), 1, 0, fg="#2c3e50")
        self.create_btn(self.tab_calc, "cos", lambda: self.press("cos("), 1, 1, fg="#2c3e50")
        self.create_btn(self.tab_calc, "tan", lambda: self.press("tan("), 1, 2, fg="#2c3e50")
        self.create_btn(self.tab_calc, "log", lambda: self.press("log("), 1, 3, fg="#2c3e50")
        self.create_btn(self.tab_calc, "√", lambda: self.press("sqrt("), 1, 4, fg="#2c3e50")
        self.create_btn(self.tab_calc, "^", lambda: self.press("^"), 1, 5, fg="#2c3e50")

        # صف التفاضل والتكامل والمتغيرات
        self.create_btn(self.tab_calc, " والمتغير x", lambda: self.press("x"), 2, 0, fg="#8e44ad")
        self.create_btn(self.tab_calc, "معادلة (=)", lambda: self.press("="), 2, 1, fg="#8e44ad")
        self.create_btn(self.tab_calc, "تفاضل d/dx", self.derivative, 2, 2, fg="#16a085")
        self.create_btn(self.tab_calc, "تكامل ∫dx", self.integral, 2, 3, fg="#16a085")
        self.create_btn(self.tab_calc, "π", lambda: self.press("pi"), 2, 4, fg="#2c3e50")
        self.create_btn(self.tab_calc, "e", lambda: self.press("E"), 2, 5, fg="#2c3e50")

        ctk.CTkLabel(self.tab_calc, text="وحدة الزوايا:", font=FONT_SMALL).grid(
            row=7, column=0, columnspan=2, padx=4, pady=4, sticky="e"
        )
        self.angle_mode_var = ctk.StringVar(value="راديان")
        self.angle_mode_menu = ctk.CTkOptionMenu(
            self.tab_calc, values=["راديان", "درجات"], variable=self.angle_mode_var,
            command=self.set_angle_mode, font=FONT_BODY
        )
        self.angle_mode_menu.grid(row=7, column=2, columnspan=2, padx=4, pady=4, sticky="ew")
        ctk.CTkLabel(self.tab_calc, text="sin/cos/tan", font=FONT_SMALL).grid(
            row=7, column=4, columnspan=2, padx=4, pady=4
        )

        # أزرار الأرقام والعمليات القياسية
        num_pad = [
            ("7", 3, 0), ("8", 3, 1), ("9", 3, 2), ("/", 3, 3), ("(", 3, 4), (")", 3, 5),
            ("4", 4, 0), ("5", 4, 1), ("6", 4, 2), ("*", 4, 3), ("%", 4, 4), ("1/x", 4, 5),
            ("1", 5, 0), ("2", 5, 1), ("3", 5, 2), ("-", 5, 3), ("x²", 5, 4), ("ارسم الدالة 📈", 5, 5),
            ("0", 6, 0), (".", 6, 1), ("00", 6, 2), ("+", 6, 3),
        ]

        for text, r, c in num_pad:
            if text == "1/x":
                self.create_btn(self.tab_calc, text, lambda: self.press("^(-1)"), r, c, fg="#2c3e50")
            elif text == "x²":
                self.create_btn(self.tab_calc, text, lambda: self.press("^2"), r, c, fg="#2c3e50")
            elif text == "ارسم الدالة 📈":
                self.create_btn(self.tab_calc, text, self.switch_and_plot, r, c, fg="#2980b9")
            elif text in "/*-+%()":
                self.create_btn(self.tab_calc, text, lambda x=text: self.press(x), r, c, fg="#2c3e50")
            else:
                self.create_btn(self.tab_calc, text, lambda x=text: self.press(x), r, c)

        # زر يساوي / حل المعادلة
        eq_btn = ctk.CTkButton(
            self.tab_calc, text="=  (احسب النتيجة / حل المعادلة)",
            command=self.calculate, height=55,
            font=(UI_FONT, 17, "bold"), fg_color="#27ae60", hover_color="#2ecc71"
        )
        eq_btn.grid(row=6, column=4, columnspan=2, padx=4, pady=4, sticky="nsew")

    # ------------------------------------------
    # تبويب 2: الرسم البياني المدمج
    # ------------------------------------------
    def setup_graph_tab(self):
        self._plot_font_scale = 1.0
        self.tab_graph.grid_rowconfigure(1, weight=1)
        self.tab_graph.grid_columnconfigure(0, weight=1)

        ctrl_frame = ctk.CTkFrame(self.tab_graph)
        ctrl_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(ctrl_frame, text="من X:", font=FONT_BODY).pack(side="left", padx=5)
        self.x_min_entry = ctk.CTkEntry(ctrl_frame, width=80, font=FONT_BODY, justify="center")
        self.x_min_entry.insert(0, "-10")
        self.x_min_entry.pack(side="left", padx=5)

        ctk.CTkLabel(ctrl_frame, text="إلى X:", font=FONT_BODY).pack(side="left", padx=5)
        self.x_max_entry = ctk.CTkEntry(ctrl_frame, width=80, font=FONT_BODY, justify="center")
        self.x_max_entry.insert(0, "10")
        self.x_max_entry.pack(side="left", padx=5)

        plot_btn = ctk.CTkButton(
            ctrl_frame, text="تحديث الرسم البياني للدالة المعروضة 📈",
            command=self.plot_graph, font=FONT_BUTTON
        )
        plot_btn.pack(side="left", padx=15, pady=8)

        # إطار الرسم البياني المدمج داخل الواجهة
        self.graph_container = ctk.CTkFrame(self.tab_graph)
        self.graph_container.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.graph_container.grid_rowconfigure(0, weight=1)
        self.graph_container.grid_columnconfigure(0, weight=1)

        self.fig, self.ax = plt.subplots(figsize=(6, 4), dpi=100)
        self.fig.patch.set_facecolor("#2b2b2b")
        self.ax.set_facecolor("#1e1e1e")
        self.ax.tick_params(colors="white", labelsize=11)
        for label in (*self.ax.get_xticklabels(), *self.ax.get_yticklabels()):
            label.set_fontname(UI_FONT)
        for spine in self.ax.spines.values():
            spine.set_color("white")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_container)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.canvas.get_tk_widget().bind("<Configure>", self.resize_plot_canvas)

    def resize_plot_canvas(self, event):
        if event.width > 0 and event.height > 0:
            self.fig.set_size_inches(event.width / self.fig.dpi, event.height / self.fig.dpi, forward=False)
            scale = max(0.75, min(1.25, min(event.width / 600, event.height / 400)))
            if abs(scale - self._plot_font_scale) >= 0.05:
                self._plot_font_scale = scale
                self.ax.tick_params(colors="white", labelsize=11 * scale)
                self.ax.xaxis.label.set_size(12 * scale)
                self.ax.yaxis.label.set_size(12 * scale)
                self.ax.title.set_size(14 * scale)
            self.canvas.draw_idle()

    # ------------------------------------------
    # تبويب 3: محول العملات والوحدات
    # ------------------------------------------
    def setup_converter_tab(self):
        self.tab_conv.grid_columnconfigure(0, weight=1)
        self.tab_conv.grid_columnconfigure(1, weight=1)
        self.tab_conv.grid_rowconfigure(0, weight=1)

        # قسم العملات
        curr_frame = ctk.CTkFrame(self.tab_conv)
        curr_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        curr_frame.grid_columnconfigure((0, 1), weight=1)
        curr_frame.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(curr_frame, text="💱 محول العملات", font=FONT_SECTION).grid(
            row=0, column=0, columnspan=2, pady=15
        )

        self.from_currency = ctk.StringVar(value="USD")
        self.to_currency = ctk.StringVar(value="SAR")

        ctk.CTkLabel(curr_frame, text="من عملة:", font=FONT_BODY).grid(row=1, column=0, pady=5)
        self.from_curr_menu = ctk.CTkOptionMenu(
            curr_frame, values=list(self.rates.keys()), variable=self.from_currency, font=FONT_BODY
        )
        self.from_curr_menu.grid(row=2, column=0, padx=10, pady=5)

        ctk.CTkLabel(curr_frame, text="إلى عملة:", font=FONT_BODY).grid(row=1, column=1, pady=5)
        self.to_curr_menu = ctk.CTkOptionMenu(
            curr_frame, values=list(self.rates.keys()), variable=self.to_currency, font=FONT_BODY
        )
        self.to_curr_menu.grid(row=2, column=1, padx=10, pady=5)

        ctk.CTkButton(curr_frame, text="احسب التحويل 💵", command=self.convert_currency, fg_color="#27ae60",
                      font=FONT_BUTTON).grid(
            row=3, column=0, padx=10, pady=15, sticky="ew"
        )
        ctk.CTkButton(curr_frame, text="تبديل العملتين 🔄", command=self.swap_currency,
                      font=FONT_BUTTON).grid(
            row=3, column=1, padx=10, pady=15, sticky="ew"
        )
        self.edit_rates_button = ctk.CTkButton(
            curr_frame, text="تعديل وحفظ أسعار الصرف ⚙️", command=self.edit_rates,
            fg_color="#d35400", font=FONT_BUTTON
        )
        self.edit_rates_button.grid(
            row=4, column=0, columnspan=2, padx=10, pady=5, sticky="ew"
        )

        self.refresh_rates_button = ctk.CTkButton(
            curr_frame, text="تحديث أسعار العملات 🌐", command=self.refresh_rates_async,
            fg_color="#356a8a", font=FONT_BUTTON
        )
        self.refresh_rates_button.grid(
            row=5, column=0, columnspan=2, padx=10, pady=5, sticky="ew"
        )

        self.rates_box = ctk.CTkTextbox(curr_frame, height=180, font=FONT_SMALL)
        self.rates_box.grid(row=6, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.update_rates_box()

        # قسم الوحدات القياسية
        unit_frame = ctk.CTkFrame(self.tab_conv)
        unit_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        unit_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(unit_frame, text="📏 محول الوحدات", font=FONT_SECTION).grid(
            row=0, column=0, columnspan=2, pady=15
        )

        ctk.CTkLabel(unit_frame, text="نوع الوحدة:", font=FONT_BODY).grid(
            row=1, column=0, columnspan=2, pady=2
        )
        self.unit_category = ctk.StringVar(value="الطول (Length)")
        cat_menu = ctk.CTkOptionMenu(
            unit_frame,
            values=["الطول (Length)", "الوزن (Weight)", "الحرارة (Temperature)"],
            variable=self.unit_category,
            command=self.update_unit_menus,
            font=FONT_BODY
        )
        self.category_menu = cat_menu
        cat_menu.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        self.from_unit = ctk.StringVar(value="m")
        self.to_unit = ctk.StringVar(value="km")

        ctk.CTkLabel(unit_frame, text="من وحدة:", font=FONT_BODY).grid(row=3, column=0, pady=5)
        self.from_unit_menu = ctk.CTkOptionMenu(
            unit_frame, values=list(LENGTH_UNITS.keys()), variable=self.from_unit, font=FONT_BODY
        )
        self.from_unit_menu.grid(row=4, column=0, padx=10, pady=5)

        ctk.CTkLabel(unit_frame, text="إلى وحدة:", font=FONT_BODY).grid(row=3, column=1, pady=5)
        self.to_unit_menu = ctk.CTkOptionMenu(
            unit_frame, values=list(LENGTH_UNITS.keys()), variable=self.to_unit, font=FONT_BODY
        )
        self.to_unit_menu.grid(row=4, column=1, padx=10, pady=5)

        ctk.CTkButton(unit_frame, text="احسب الوحدة 📐", command=self.convert_units, fg_color="#27ae60",
                      font=FONT_BUTTON).grid(
            row=5, column=0, padx=10, pady=15, sticky="ew"
        )
        ctk.CTkButton(unit_frame, text="تبديل الوحدتين 🔄", command=self.swap_units,
                      font=FONT_BUTTON).grid(
            row=5, column=1, padx=10, pady=15, sticky="ew"
        )

        info_text = (
            "💡 طريقة الاستخدام:\n"
            "1. اكتب القيمة الرقمية في شاشة الحاسبة.\n"
            "2. اختر العملة أو نوع الوحدة المطلوبة.\n"
            "3. اضغط على زر التحويل لعرض النتيجة وتسجيلها في السجل."
        )
        self.info_lbl = ctk.CTkLabel(
            unit_frame, text=info_text, justify="right", anchor="e", font=FONT_BODY, wraplength=420
        )
        self.info_lbl.grid(row=6, column=0, columnspan=2, padx=15, pady=20)
        self.tab_conv.bind("<Configure>", self.resize_converter_text, add="+")

    def resize_converter_text(self, event):
        if event.width > 0:
            self.info_lbl.configure(wraplength=max(220, min(420, (event.width - 80) // 2)))

    # ==========================================
    # الدوال المساعدة والأزرار
    # ==========================================
    def create_btn(self, parent, text, cmd, r, c, fg=None):
        kwargs = {"text": text, "command": cmd, "height": 50, "font": FONT_BUTTON}
        if fg:
            kwargs["fg_color"] = fg
        btn = ctk.CTkButton(parent, **kwargs)
        btn.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
        return btn

    @staticmethod
    def button_help_text(text):
        if text.isdigit():
            return f"يُدرج الرقم {text} في التعبير الظاهر."
        operator_help = {
            "+": "يجمع القيمتين. أدخل العدد التالي ثم احسب.",
            "-": "يطرح العدد التالي من القيمة السابقة.",
            "*": "يضرب القيمتين.",
            "/": "يقسم القيمة السابقة على العدد التالي.",
            "%": "يحسب باقي القسمة.",
            "(": "يبدأ مجموعة حسابية داخل أقواس.",
            ")": "ينهي المجموعة الحسابية داخل الأقواس.",
            ".": "يُدرج العلامة العشرية.",
            "00": "يُدرج صفرين في التعبير.",
        }
        if text in operator_help:
            return operator_help[text]
        descriptions = {
            "MC": "يمسح القيمة المحفوظة في الذاكرة.",
            "MR": "يسترجع القيمة المحفوظة ويضيفها إلى شاشة الحساب.",
            "M+": "يضيف الرقم الظاهر إلى الذاكرة.",
            "M-": "يطرح الرقم الظاهر من الذاكرة.",
            "C (مسح)": "يمسح التعبير الحالي من الشاشة.",
            "⌫": "يحذف آخر رمز من التعبير الحالي.",
            "sin": "يبدأ حساب جيب الزاوية؛ أدخل القيمة ثم أغلق القوس. وحدة الزاوية محددة أسفل اللوحة.",
            "cos": "يبدأ حساب جيب تمام الزاوية؛ أدخل القيمة ثم أغلق القوس.",
            "tan": "يبدأ حساب ظل الزاوية؛ أدخل القيمة ثم أغلق القوس.",
            "log": "يحسب اللوغاريتم الطبيعي (أساس e) للقيمة داخل القوس.",
            "√": "يحسب الجذر التربيعي للقيمة داخل القوس.",
            "^": "يرفع العدد إلى الأس الذي تدخله بعد هذا الزر.",
            " والمتغير x": "يُدرج المتغير x لاستخدامه في المعادلات والتفاضل والتكامل والرسم.",
            "معادلة (=)": "يُدرج علامة المساواة؛ أدخل معادلة تحتوي x ثم اضغط زر الحساب لحلها.",
            "تفاضل d/dx": "يحسب المشتقة الرمزية للتعبير الظاهر بالنسبة إلى x.",
            "تكامل ∫dx": "يحسب التكامل غير المحدد للتعبير الظاهر بالنسبة إلى x.",
            "π": "يُدرج ثابت باي.",
            "e": "يُدرج ثابت أويلر e.",
            "1/x": "يأخذ مقلوب العدد الحالي؛ أكمل التعبير ثم احسب.",
            "x²": "يرفع التعبير الحالي إلى القوة الثانية.",
            "ارسم الدالة 📈": "يفتح تبويب الرسم ويرسم الدالة الظاهرة بالنسبة إلى x.",
            "=  (احسب النتيجة / حل المعادلة)": "يحسب التعبير أو يحل معادلة في x إذا احتوت على علامة مساواة.",
            "حول البرنامج ℹ️": "يعرض معلومات الإصدار والميزات ووسائل التواصل.",
            "مسح السجل 🗑️": "يمسح سجل العمليات المعروض في اللوحة الجانبية.",
            "تحديث الرسم البياني للدالة المعروضة 📈": "يرسم الدالة الظاهرة باستخدام حدود x المحددة.",
            "تحديث أسعار العملات 🌐": "يجلب أحدث أسعار مرجعية متاحة من Frankfurter عبر الإنترنت ويحفظ تاريخ البيانات. لا تمثل هذه الأسعار عروض بيع وشراء لحظية.",
            "احسب التحويل 💵": "يحوّل المبلغ الظاهر بين العملتين المختارتين.",
            "تبديل العملتين 🔄": "يعكس عملة المصدر وعملة الوجهة.",
            "تعديل وحفظ أسعار الصرف ⚙️": "يتيح إدخال أسعار يدوية؛ القيمة المطلوبة هي مقدار الدولار لكل وحدة من العملة.",
            "احسب الوحدة 📐": "يحوّل القيمة الظاهرة بين الوحدتين المختارتين.",
            "تبديل الوحدتين 🔄": "يعكس وحدة المصدر ووحدة الوجهة.",
            "حفظ التعديلات 💾": "يتحقق من أسعار الصرف ويحفظها على هذا الجهاز.",
        }
        return descriptions.get(text, "زر إدخال: يضيف هذا الرمز إلى التعبير الظاهر.")

    def set_angle_mode(self, choice):
        self.angle_mode = "Degrees" if choice == "درجات" else "Radians"

    def format_number(self, value):
        try:
            num = float(value)
            if not math.isfinite(num):
                return str(value)
            if num.is_integer():
                return str(int(num))
            return format(num, ".12g")
        except Exception:
            return str(value)

    def add_history(self, text):
        self.history_box.insert("end", text + "\n")
        self.history_box.see("end")

    def clear_history(self):
        self.history_box.delete("1.0", "end")

    # ==========================================
    # العمليات الحسابية والعلمية
    # ==========================================
    def press(self, v):
        if self.result_shown and str(v) not in "+-*/^%=":
            self.expression = ""
        self.result_shown = False
        self.expression += str(v)
        self.display_var.set(self.expression)

    def clear(self):
        self.expression = ""
        self.result_shown = False
        self.display_var.set("")

    def backspace(self):
        if self.result_shown:
            self.clear()
            return
        self.expression = self.expression[:-1]
        self.display_var.set(self.expression)

    def calculate(self):
        try:
            raw_expr = self.display_var.get().strip()
            if not raw_expr:
                return

            expr = raw_expr.replace("^", "**")

            if "=" in expr:
                x = symbols("x")
                left, right = expr.split("=", 1)
                lhs = parse_expression(left, self.angle_mode)
                rhs = parse_expression(right, self.angle_mode)
                if x not in lhs.free_symbols.union(rhs.free_symbols):
                    result = "العبارة صحيحة" if lhs == rhs else "لا يوجد حل"
                else:
                    eq = Eq(lhs, rhs, evaluate=False)
                    sol = solve(eq, x)
                    result = f"x = {sol}"
            else:
                parsed = parse_expression(expr, self.angle_mode)
                evaluated = parsed.evalf()
                if evaluated.free_symbols:
                    result = str(parsed)
                elif evaluated.is_finite is False:
                    raise ValueError("النتيجة غير منتهية؛ تحقق من القسمة على صفر")
                elif evaluated.is_real is False:
                    result = str(evaluated)
                else:
                    result = self.format_number(evaluated)

            self.display_var.set(result)
            self.add_history(f"{raw_expr} ➔ {result}")
            self.expression = result if not result.startswith("x =") else ""
            self.result_shown = True

        except Exception as e:
            self.display_var.set(f"خطأ: {str(e)[:80]}")
            self.expression = ""
            self.result_shown = True

    def derivative(self):
        try:
            raw = self.display_var.get().replace("^", "**")
            x = symbols("x")
            expr = parse_expression(raw, self.angle_mode)
            res = str(diff(expr, x)).replace("**", "^")
            self.display_var.set(res)
            self.expression = res
            self.result_shown = True
            self.add_history(f"d/dx({raw}) = {res}")
        except Exception as e:
            self.display_var.set(f"خطأ التفاضل: {str(e)[:60]}")
            self.expression = ""

    def integral(self):
        try:
            raw = self.display_var.get().replace("^", "**")
            x = symbols("x")
            expr = parse_expression(raw, self.angle_mode)
            res = str(integrate(expr, x)).replace("**", "^")
            self.display_var.set(res + " + C")
            self.expression = res
            self.result_shown = True
            self.add_history(f"∫({raw})dx = {res}")
        except Exception as e:
            self.display_var.set(f"خطأ التكامل: {str(e)[:60]}")
            self.expression = ""

    # ==========================================
    # الرسم البياني السريع (NumPy + Lambdify)
    # ==========================================
    def switch_and_plot(self):
        self.tabview.set("الرسم البياني للدوال")
        self.plot_graph()

    def plot_graph(self):
        try:
            raw_expr = self.display_var.get().strip()
            if not raw_expr or "Error" in raw_expr or raw_expr.startswith("خطأ"):
                raw_expr = "sin(x)"
                self.display_var.set(raw_expr)
                self.expression = raw_expr

            if "=" in raw_expr:
                raw_expr = raw_expr.split("=")[0]

            expr_str = raw_expr.replace("^", "**")
            x = symbols("x")
            sym_expr = parse_expression(expr_str, self.angle_mode)

            x_min = float(self.x_min_entry.get())
            x_max = float(self.x_max_entry.get())
            if not math.isfinite(x_min) or not math.isfinite(x_max) or x_min >= x_max:
                raise ValueError("أدخل حدين صالحين بحيث يكون الحد الأدنى أصغر من الأعلى")
            x_vals = np.linspace(x_min, x_max, 500)

            # استخدام lambdify لأداء فائق السرعة بدلاً من حلقات التكرار
            f_num = lambdify(x, sym_expr, modules=["numpy"])
            y_vals = f_num(x_vals)

            if np.isscalar(y_vals):
                y_vals = np.full_like(x_vals, float(y_vals))
            y_vals = np.asarray(y_vals, dtype=float)
            if y_vals.shape != x_vals.shape:
                raise ValueError("تعذر إنشاء قيم الرسم لهذه الدالة")
            y_vals = np.where(np.isfinite(y_vals), y_vals, np.nan)
            if np.all(np.isnan(y_vals)):
                raise ValueError("لا توجد قيم حقيقية قابلة للرسم ضمن هذا النطاق")

            self.ax.clear()
            self.ax.set_facecolor("#1e1e1e")
            for spine in self.ax.spines.values():
                spine.set_color("white")
            self.ax.plot(x_vals, y_vals, color="#3498db", linewidth=2.2, label=f"f(x) = {raw_expr}")
            self.ax.axhline(0, color="#7f8c8d", linewidth=1)
            self.ax.axvline(0, color="#7f8c8d", linewidth=1)
            self.ax.grid(True, linestyle="--", alpha=0.4)
            self.ax.tick_params(colors="white", labelsize=11 * self._plot_font_scale)
            for label in (*self.ax.get_xticklabels(), *self.ax.get_yticklabels()):
                label.set_fontname(UI_FONT)
            self.ax.set_xlabel("x", color="white", fontname=UI_FONT, fontsize=12 * self._plot_font_scale)
            self.ax.set_ylabel("f(x)", color="white", fontname=UI_FONT, fontsize=12 * self._plot_font_scale)
            self.ax.set_title(
                f"f(x) = {raw_expr}", color="white", fontname=UI_FONT,
                fontsize=14 * self._plot_font_scale, fontweight="bold"
            )
            self.ax.legend(
                facecolor="#2b2b2b", edgecolor="white", labelcolor="white",
                prop={"family": UI_FONT, "size": 11 * self._plot_font_scale}
            )
            self.canvas.draw()

            self.add_history(f"Plotted: f(x) = {raw_expr}")
        except Exception as e:
            self.display_var.set(f"خطأ الرسم: {str(e)[:60]}")
            self.expression = ""

    # ==========================================
    # إدارة الذاكرة (Memory Functions)
    # ==========================================
    def update_mem_label(self):
        self.mem_label.configure(text=f"الذاكرة (Memory): {self.format_number(self.memory)}")

    def memory_add(self):
        try:
            value = float(self.display_var.get())
            result = self.memory + value
            if not math.isfinite(value) or not math.isfinite(result):
                raise ValueError
            self.memory = result
            self.update_mem_label()
        except (ValueError, OverflowError):
            messagebox.showerror("قيمة غير صالحة", "أدخل نتيجة رقمية محدودة لإضافتها إلى الذاكرة.", parent=self)

    def memory_sub(self):
        try:
            value = float(self.display_var.get())
            result = self.memory - value
            if not math.isfinite(value) or not math.isfinite(result):
                raise ValueError
            self.memory = result
            self.update_mem_label()
        except (ValueError, OverflowError):
            messagebox.showerror("قيمة غير صالحة", "أدخل نتيجة رقمية محدودة لطرحها من الذاكرة.", parent=self)

    def memory_recall(self):
        self.press(self.format_number(self.memory))

    def memory_clear(self):
        self.memory = 0.0
        self.update_mem_label()

    # ==========================================
    # تحويل العملات والوحدات
    # ==========================================
    def update_rates_box(self):
        self.rates_box.configure(state="normal")
        self.rates_box.delete("1.0", "end")
        self.rates_box.insert(
            "end", f"المصدر: {self.rate_source}\nتاريخ البيانات: {self.rate_date}\n"
            "الأسعار مرجعية وليست عروض بيع وشراء لحظية.\n" + "-" * 32 + "\n"
        )
        for k, v in self.rates.items():
            self.rates_box.insert("end", f"1 {k:<4} = {v} USD\n")
        self.rates_box.configure(state="disabled")

    def convert_currency(self):
        try:
            val = float(self.display_var.get())
            if not math.isfinite(val):
                raise ValueError("أدخل مبلغًا رقميًا محدودًا")
            f = self.from_currency.get()
            t = self.to_currency.get()

            # تصحيح المعادلة الرياضية: القيمة * (قيمة عملة المصدر بالدولار / قيمة عملة الهدف بالدولار)
            usd_value = val * self.rates[f]
            result = usd_value / self.rates[t]
            if not math.isfinite(result):
                raise ValueError("نتيجة التحويل خارج النطاق الرقمي")
            formatted = self.format_number(result)

            self.display_var.set(formatted)
            self.expression = formatted
            self.result_shown = True
            self.add_history(f"{val} {f} = {formatted} {t}")
        except Exception as e:
            self.display_var.set(f"خطأ العملة: {str(e)[:60]}")
            self.expression = ""
