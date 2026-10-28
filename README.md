# Calculator Pro

A desktop scientific calculator built with Python and CustomTkinter. It combines everyday calculations with symbolic mathematics, graph plotting, unit conversion, and configurable currency conversion in a dark-themed interface.

**الحاسبة الاحترافية** تطبيق سطح مكتب مبني بلغة Python، يجمع بين العمليات الحسابية والرياضيات الرمزية ورسم الدوال وتحويل الوحدات والعملات، ضمن واجهة داكنة.

## Features

- **Scientific calculations** using SymPy, including expressions such as `sin(`, `cos(`, `tan(`, `log(`, `sqrt(`, powers (`^`), and parentheses.
- **Equation solving** for expressions written as an equation with `=`.
- **Symbolic differentiation** with the `diff` button.
- **Symbolic integration** with the `∫` button.
- **Function plotting** over an x-range from -10 to 10 using Matplotlib.
- **Unit conversion** for length, weight, and selected temperature conversions.
- **Currency conversion** using editable exchange-rate values.
- **Calculation history** and memory controls (`MC`, `MR`, `M+`, `M-`).
- **Keyboard support** for numbers, basic operators, Enter, Backspace, and Escape.

## Requirements

- Python 3.10 or later recommended
- `customtkinter`
- `numpy`
- `matplotlib`
- `sympy`

## Installation

1. Install Python from [python.org](https://www.python.org/downloads/) if it is not already installed.
2. Clone the repository:

   ```bash
   git clone https://github.com/aboomarye-blip/calculator-pro-v2.git
   cd calculator-pro-v2
   ```

3. (Recommended) Create and activate a virtual environment:

   **Windows**
   ```powershell
   py -m venv .venv
   .venv\\Scripts\\Activate.ps1
   ```

   **macOS / Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. Install the dependencies:

   ```bash
   python -m pip install customtkinter numpy matplotlib sympy
   ```

5. Run the application:

   ```bash
   python calculator_pro.py
   ```

## Usage notes

- Enter an expression and press **=** or **Enter** to calculate it.
- Use the **Graph**, **diff**, and **∫** buttons for plotting, differentiation, and integration.
- Select source and target units or currencies in the dropdown menus before converting the value shown in the display.
- Currency rates are example values stored in the source code; they are **not live market rates**. Use **Edit Exchange Rates** to update them before relying on conversions.
- The graphing and desktop interface require a graphical desktop session.

## Project status

This is an early-stage project. Features and behavior may change as the project develops. Please test calculations and conversion values before using them for important work.

## Author

**Abdullah Mahyoub**

## Repository

https://github.com/aboomarye-blip/calculator-pro-v2

---

# الحاسبة الاحترافية

### المميزات
- العمليات الحسابية والدوال العلمية.
- حل المعادلات الرياضية.
- التفاضل والتكامل الرمزي.
- رسم الدوال البيانية.
- تحويل وحدات الطول والوزن وبعض وحدات الحرارة.
- تحويل العملات مع إمكانية تعديل أسعار الصرف.
- سجل العمليات وذاكرة الآلة الحاسبة.

### التشغيل
بعد تثبيت Python والمكتبات المطلوبة، نفّذ:

```bash
python -m pip install customtkinter numpy matplotlib sympy
python calculator_pro.py
```

**تنبيه:** أسعار العملات الافتراضية داخل البرنامج ليست أسعارًا مباشرة أو محدثة تلقائيًا. يرجى تحديثها يدويًا قبل استخدامها.
