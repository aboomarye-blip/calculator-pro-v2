# Calculator Pro V2.2

A desktop scientific and engineering calculator built with Python and CustomTkinter. It includes scientific calculations, equation solving, symbolic differentiation and integration, function plotting, currency conversion, unit conversion, calculation history, and memory controls.

**الحاسبة الاحترافية** تطبيق سطح مكتب بلغة Python بواجهة عربية، يجمع بين العمليات العلمية ورسم الدوال والتفاضل والتكامل وتحويل العملات والوحدات.

## Features

- Scientific calculations using a restricted expression parser.
- Equation solving for equations containing `x`.
- Symbolic differentiation and integration with SymPy.
- Function plotting with NumPy and Matplotlib.
- Currency conversion for USD, SAR, YER, QAR, EUR, and GBP.
- Manual exchange-rate editing and reference-rate refresh through Frankfurter.
- Length, weight, and temperature conversion.
- Calculation history, memory controls, keyboard shortcuts, and context help.
- Persistent exchange-rate settings stored in the user's application data directory.

## Requirements

- Python 3.10 or newer
- A desktop environment with Tk support

Install dependencies from `requirements.txt`.

## Installation

1. Install Python from [python.org](https://www.python.org/downloads/).
2. Clone the repository:

   ```bash
   git clone https://github.com/aboomarye-blip/calculator-pro-v2.git
   cd calculator-pro-v2
   ```

3. (Recommended) Create and activate a virtual environment.

   **Windows PowerShell**
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   **macOS / Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Run the application:

   ```bash
   python calculator_pro_v2.2.py
   ```

## Exchange-rate note

Built-in exchange rates are approximate defaults. The application can retrieve reference rates from Frankfurter when internet access is available, and also allows manual editing. These are reference rates, not real-time bank buy/sell quotations. Verify rates before financial use.

## Project files

- `calculator_pro_v2.2.py` — application source
- `requirements.txt` — Python dependencies
- `.gitignore` — common local files excluded from version control

## العربية

### التشغيل

```bash
python -m pip install -r requirements.txt
python calculator_pro_v2.2.py
```

**تنبيه:** أسعار الصرف الافتراضية تقريبية، والأسعار المرجعية ليست عروض بيع وشراء مصرفية لحظية. تحقّق منها قبل استخدامها في المعاملات المالية.

## Author

Abdullah Mahyoub
