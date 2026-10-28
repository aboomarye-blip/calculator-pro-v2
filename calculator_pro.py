import customtkinter as ctk
import numpy as np
import matplotlib.pyplot as plt
from sympy import *
import webbrowser

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("Calculator Pro")
app.geometry("1000x650")

expression = ""
memory = 0
result_shown = False

display_var = ctk.StringVar()

# =========================
# اسعار العملات
# =========================

rates = {
"USD":1,
"SAR":0.26109661,
"YER":0.00186567,
"QAR":0.00063452
}

# =========================
# الوحدات
# =========================

length_units = {
"km":1000,
"m":1,
"cm":0.01,
"mm":0.001,
"inch":0.0254,
"ft":0.3048
}

weight_units = {
"kg":1,
"g":0.001,
"lb":0.453592
}

temp_units = ["C","F","K"]

# =========================
# تنسيق الارقام
# =========================

def format_number(value):

    try:
        num=float(value)

        if num.is_integer():
            return str(int(num))

        return ('%.10f' % num).rstrip('0').rstrip('.')

    except:
        return str(value)

# =========================
# شاشة العرض
# =========================

display = ctk.CTkEntry(
app,
textvariable=display_var,
font=("Segoe UI",36),
justify="right",
height=70
)

display.grid(row=0,column=0,columnspan=6,padx=10,pady=20,sticky="nsew")

# =========================
# HISTORY
# =========================

history_box = ctk.CTkTextbox(app,width=220,font=("Consolas",12))
history_box.grid(row=0,column=6,rowspan=8,padx=10,pady=10,sticky="nsew")

def add_history(t):
    history_box.insert("end",t+"\n")
    history_box.see("end")

def clear_history():
    history_box.delete("1.0","end")

# =========================
# العمليات
# =========================

def press(v):

    global expression,result_shown

    if result_shown and v not in "+-*/^":
        expression=""

    result_shown=False
    expression+=str(v)

    display_var.set(expression)

def clear():
    global expression
    expression=""
    display_var.set("")

def backspace():
    global expression
    expression=expression[:-1]
    display_var.set(expression)

# =========================
# الحساب
# =========================

def calculate():

    global expression,result_shown

    try:

        if expression.strip()=="":
            return

        expr=expression.replace("^","**")

        if "=" in expr:

            x=symbols("x")

            left,right=expr.split("=")

            eq=Eq(sympify(left),sympify(right))

            sol=solve(eq)

            result=str(sol)

        else:

            result=format_number(sympify(expr).evalf())

        display_var.set(result)

        add_history(expr+" = "+result)

        expression=result
        result_shown=True

    except:

        display_var.set("Error")
        expression=""

# =========================
# التفاضل
# =========================

def derivative():

    try:

        x=symbols("x")

        expr=sympify(display_var.get())

        result=diff(expr,x)

        display_var.set(result)

    except:

        display_var.set("Derivative Error")

# =========================
# التكامل
# =========================

def integral():

    try:

        x=symbols("x")

        expr=sympify(display_var.get())

        result=integrate(expr,x)

        display_var.set(result)

    except:

        display_var.set("Integral Error")

# =========================
# الرسم
# =========================

def plot_graph():

    try:

        expr=display_var.get().replace("^","**")

        x=symbols("x")

        f=sympify(expr)

        x_vals=np.linspace(-10,10,400)

        y_vals=[]

        for val in x_vals:

            try:

                y=f.subs(x,val)
                y_vals.append(float(y))

            except:

                y_vals.append(np.nan)

        plt.figure("Graph")

        plt.plot(x_vals,y_vals)

        plt.axhline(0)
        plt.axvline(0)

        plt.grid(True)

        plt.title(expr)

        plt.show()

    except:

        display_var.set("Graph Error")

# =========================
# تحويل العملات
# =========================

from_currency = ctk.StringVar(value="USD")
to_currency = ctk.StringVar(value="SAR")

def edit_rates():

    win = ctk.CTkToplevel(app)
    win.title("Edit Exchange Rates")
    win.geometry("350x400")

    entries={}

    row=0

    for k,v in rates.items():

        ctk.CTkLabel(win,text=k).grid(row=row,column=0,padx=10,pady=10)

        e=ctk.CTkEntry(win)
        e.insert(0,str(v))
        e.grid(row=row,column=1,padx=10,pady=10)

        entries[k]=e

        row+=1


    def save_rates():

        for k,e in entries.items():

            try:
                rates[k]=float(e.get())
            except:
                pass

        update_rates_box()
        win.destroy()


    save_btn = ctk.CTkButton(win,text="Save",command=save_rates)
    save_btn.grid(row=row,column=0,columnspan=2,pady=20)
def convert_currency():

    try:

        value=float(display_var.get())

        f=from_currency.get()
        t=to_currency.get()

        result=value*(rates[t]/rates[f])

        display_var.set(format_number(result))

    except:

        display_var.set("Currency Error")

def swap_currency():

    a=from_currency.get()
    b=to_currency.get()

    from_currency.set(b)
    to_currency.set(a)

# =========================
# تحويل الوحدات
# =========================

from_unit = ctk.StringVar(value="m")
to_unit = ctk.StringVar(value="km")

def convert_units():

    try:

        value=float(display_var.get())

        f=from_unit.get()
        t=to_unit.get()

        if f in length_units and t in length_units:

            result=value*(length_units[f]/length_units[t])

        elif f in weight_units and t in weight_units:

            result=value*(weight_units[f]/weight_units[t])

        elif f=="C" and t=="F":

            result=(value*9/5)+32

        elif f=="F" and t=="C":

            result=(value-32)*5/9

        elif f=="C" and t=="K":

            result=value+273.15

        elif f=="K" and t=="C":

            result=value-273.15

        else:

            display_var.set("Unit Error")
            return

        display_var.set(format_number(result))

    except:

        display_var.set("Unit Error")

def swap_units():

    a=from_unit.get()
    b=to_unit.get()

    from_unit.set(b)
    to_unit.set(a)
# =========================
# لوحة المفاتيح
# =========================

def key_input(event):

    k=event.char

    if k in "0123456789+-*/().":
        press(k)

    elif k=="^":
        press("^")

def key_enter(event=None):
    calculate()

def key_backspace(event=None):
    backspace()

def key_escape(event=None):
    clear()

app.bind("<Key>",key_input)
app.bind("<Return>",key_enter)
app.bind("<KP_Enter>",key_enter)
app.bind("<BackSpace>",key_backspace)
app.bind("<Escape>",key_escape)

app.bind("<Control-c>",lambda e: copy_value())
app.bind("<Control-v>",lambda e: paste_value())

# =========================
# نافذة About
# =========================

def open_whatsapp():
    webbrowser.open("https://wa.me/967777491747")

def show_about():

    about = ctk.CTkToplevel(app)
    about.title("About Calculator Pro")
    about.geometry("420x420")

    title = ctk.CTkLabel(about,text="Calculator Pro",font=("Segoe UI",24,"bold"))
    title.pack(pady=10)

    version = ctk.CTkLabel(about,text="الإصدار 1.0",font=("Segoe UI",16))
    version.pack()

    desc = ctk.CTkLabel(about,text="برنامج آلة حاسبة علمية متقدمة",font=("Segoe UI",14))
    desc.pack(pady=10)

    features = ctk.CTkLabel(
    about,
    text="""المميزات:
• إجراء العمليات الحسابية العلمية
• رسم الدوال البيانية
• حل المعادلات الرياضية
• تحويل الوحدات المختلفة
• تحويل العملات""",
    justify="right"
    )

    features.pack(pady=10)

    dev = ctk.CTkLabel(about,text="المطور:\nعبدالله مهيوب",font=("Segoe UI",14))
    dev.pack(pady=10)

    whatsapp = ctk.CTkButton(about,text="واتساب: +967777491747",command=open_whatsapp)
    whatsapp.pack(pady=10)

    copy = ctk.CTkLabel(about,text="© 2026 جميع الحقوق محفوظة")
    copy.pack(pady=10)

# =========================
# إنشاء زر
# =========================

def btn(t,cmd,r,c):

    b=ctk.CTkButton(app,text=t,command=cmd,height=45,font=("Segoe UI",14))
    b.grid(row=r,column=c,padx=4,pady=4,sticky="nsew")

# =========================
# الذاكرة
# =========================

def memory_add():
    global memory
    memory+=float(display_var.get())

def memory_sub():
    global memory
    memory-=float(display_var.get())

def memory_recall():
    press(memory)

def memory_clear():
    global memory
    memory=0

btn("MC",memory_clear,1,0)
btn("MR",memory_recall,1,1)
btn("M+",memory_add,1,2)
btn("M-",memory_sub,1,3)

btn("sin",lambda:press("sin("),1,4)
btn("cos",lambda:press("cos("),1,5)

btn("tan",lambda:press("tan("),2,4)
btn("log",lambda:press("log("),2,5)

btn("√",lambda:press("sqrt("),3,4)
btn("Graph",plot_graph,3,5)

btn("diff",derivative,4,4)
btn("∫",integral,4,5)


# =========================
# الأرقام
# =========================

buttons=[
("7","7"),("8","8"),("9","9"),("/","/"),
("4","4"),("5","5"),("6","6"),("*","*"),
("1","1"),("2","2"),("3","3"),("-","-"),
("0","0"),(".","."),("(","("),(")",")"),
("+","+"),("^","^"),("%","%"),("⌫","back")
]

row=2
col=0

for t,v in buttons:

    if v=="back":
        btn(t,backspace,row,col)
    else:
        btn(t,lambda x=v:press(x),row,col)

    col+=1

    if col==4:
        col=0
        row+=1

equals=ctk.CTkButton(app,text="=",command=calculate,height=60,font=("Segoe UI",18))
equals.grid(row=7,column=0,columnspan=4,padx=5,pady=10,sticky="nsew")

# =========================
# العملات
# =========================

from_menu=ctk.CTkOptionMenu(app,values=list(rates.keys()),variable=from_currency)
to_menu=ctk.CTkOptionMenu(app,values=list(rates.keys()),variable=to_currency)

from_menu.grid(row=8,column=0,columnspan=2,padx=5,pady=5)
to_menu.grid(row=8,column=2,columnspan=2,padx=5,pady=5)

b=ctk.CTkButton(app,text="احسب سعر الصرف",command=convert_currency,height=45,width=160,font=("Segoe UI",14))
b.grid(row=8,column=4,padx=4,pady=4,sticky="nsew")
btn("تحويل العملة",swap_currency,8,5)
btn("تعديل سعر الصرف",edit_rates,8,6)

# =========================
# الوحدات
# =========================

all_units=list(length_units.keys())+list(weight_units.keys())+temp_units

from_unit_menu=ctk.CTkOptionMenu(app,values=all_units,variable=from_unit)
to_unit_menu=ctk.CTkOptionMenu(app,values=all_units,variable=to_unit)

from_unit_menu.grid(row=9,column=0,columnspan=2,padx=5,pady=5)
to_unit_menu.grid(row=9,column=2,columnspan=2,padx=5,pady=5)

btn("احسب الوحدة",convert_units,9,4)
btn("تحويل الوحدة",swap_units,9,5)

# =========================
# لوحات المعلومات
# =========================

rates_box=ctk.CTkTextbox(app,width=200,height=120,font=("Consolas",12))
rates_box.grid(row=10,column=0,columnspan=2,padx=10,pady=10,sticky="nsew")
rates_box.configure(state="disabled")
def update_rates_box():

    rates_box.configure(state="normal")

    rates_box.delete("1.0","end")

    rates_box.insert("end","Exchange Rates\n\n")

    for k,v in rates.items():
        rates_box.insert("end",f"{k} : {v}\n")

    rates_box.configure(state="disabled")


update_rates_box()


units_box=ctk.CTkTextbox(app,width=200,height=120,font=("Consolas",12))
units_box.grid(row=10,column=2,columnspan=2,padx=10,pady=10,sticky="nsew")
units_box.insert("end","Units\n\n")

for u in all_units:
    units_box.insert("end",u+"\n")

btn("Clear History",clear_history,10,5)

# =========================
# resize
# =========================

for i in range(15):
    app.rowconfigure(i,weight=1)

for i in range(7):
    app.columnconfigure(i,weight=1)

btn("About",show_about,11,6)

app.mainloop()