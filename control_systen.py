import tkinter as tk
from tkinter import messagebox
import json
import hashlib
import os
import serial
import serial.tools.list_ports
import threading
import time

paleta_de_colores = {
    "bg":      "#0d1117",
    "panel":   "#161b22",
    "card":    "#1c2128",
    "border":  "#30363d",
    "accent":  "#00d4aa",
    "danger":  "#f85149",
    "text":    "#e6edf3",
    "muted":   "#8b949e",
    "on":      "#238636",
    "warning": "#e3b341",
    "accent2": "#0ea5e9",
}

BAUD = 115200

ventana = tk.Tk()
ventana.title("Automatic system")
ventana.geometry("1200x800")
ventana.configure(bg=paleta_de_colores["bg"])

ARCHIVO_USUARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usuario.json")

intentos          = 0
puerto_serial     = None
leyendo           = False
_temp_var         = None
_lbl_alarma       = None
_lbl_huella       = None
_datos_registro   = {}  # guarda temporalmente nombre y contraseña mientras se registra huella

# ── SERIAL ─────────────────────────────
def encontrar_puerto_pico():
    for p in serial.tools.list_ports.comports():
        if p.vid and hex(p.vid).upper() == "0X2E8A":
            return p.device
        if "ttyACM" in p.device or "Pico" in (p.description or ""):
            return p.device
    return None

def conectar_automatico():
    global puerto_serial
    puerto = encontrar_puerto_pico()
    if puerto:
        try:
            puerto_serial = serial.Serial(puerto, BAUD, timeout=1)
        except Exception:
            pass

def enviar_comando(comando):
    global puerto_serial
    if puerto_serial and puerto_serial.is_open:
        try:
            msg = json.dumps({"cmd": comando, "val": 1}) + "\n"
            puerto_serial.write(msg.encode())
        except Exception:
            pass

# ── HILO LECTURA ───────────────────────
def iniciar_hilo_lectura():
    global leyendo
    leyendo = True
    t = threading.Thread(target=_leer_loop, daemon=True)
    t.start()

def _leer_loop():
    global puerto_serial, _temp_var, _lbl_alarma, _lbl_huella, _datos_registro
    while leyendo:
        try:
            if puerto_serial and puerto_serial.is_open and puerto_serial.in_waiting:
                linea = puerto_serial.readline().decode().strip()
                if not linea:
                    continue
                data   = json.loads(linea)
                evento = data.get("evento")
                val    = data.get("val")

                if evento == "TEMPERATURA" and _temp_var:
                    _temp_var.set(f"🌡 {val} °C")

                elif evento == "MOVIMIENTO" and _lbl_alarma:
                    _lbl_alarma.config(
                        text="⚠ MOVIMIENTO DETECTADO",
                        fg=paleta_de_colores["danger"])

                elif evento == "ALARMA_DESACTIVADA" and _lbl_alarma:
                    _lbl_alarma.config(
                        text="● Sin movimiento",
                        fg=paleta_de_colores["on"])

                elif evento == "HUELLA_OK":
                    # Login con huella: buscar usuario por ID
                    usuarios = cargar_usuarios()
                    nombre_encontrado = None
                    for nombre, datos in usuarios.items():
                        if isinstance(datos, dict):
                            if datos.get("huella_id") == val:
                                nombre_encontrado = nombre
                                break
                    if nombre_encontrado:
                        ventana.after(0, lambda n=nombre_encontrado: mostrar_panel(n))
                    elif _lbl_huella:
                        _lbl_huella.config(
                            text="✖ Huella no registrada",
                            fg=paleta_de_colores["danger"])

                elif evento == "HUELLA_REGISTRADA":
                    # El Pico devuelve el ID con el que guardó la huella
                    # Guardamos el usuario con ese ID
                    if _datos_registro:
                        nombre   = _datos_registro.get("nombre")
                        password = _datos_registro.get("password")
                        if nombre and password:
                            usuarios = cargar_usuarios()
                            usuarios[nombre] = {
                                "password":  password,
                                "huella_id": val
                            }
                            with open(ARCHIVO_USUARIO, "w") as f:
                                json.dump(usuarios, f)
                            _datos_registro.clear()
                    if _lbl_huella:
                        _lbl_huella.config(
                            text="✔ Huella registrada",
                            fg=paleta_de_colores["on"])

                elif evento == "HUELLA_ERROR" and _lbl_huella:
                    _lbl_huella.config(
                        text=f"✖ {val}",
                        fg=paleta_de_colores["danger"])

                elif evento == "HUELLA_FAIL" and _lbl_huella:
                    _lbl_huella.config(
                        text="✖ Huella no reconocida",
                        fg=paleta_de_colores["danger"])

                elif evento == "HUELLA_MSG" and _lbl_huella:
                    _lbl_huella.config(
                        text=f"☛ {val}",
                        fg=paleta_de_colores["accent2"])

        except Exception:
            pass
        time.sleep(0.05)

# ── USUARIOS ───────────────────────────
def cargar_usuarios():
    if os.path.exists(ARCHIVO_USUARIO):
        with open(ARCHIVO_USUARIO, "r") as f:
            return json.load(f)
    return {}

def verificar_login(nombre, contrasena):
    global intentos
    usuarios = cargar_usuarios()
    if nombre in usuarios:
        datos = usuarios[nombre]
        pwd = datos.get("password") if isinstance(datos, dict) else datos
        h = hashlib.sha256(contrasena.encode()).hexdigest()
        if pwd == h:
            intentos = 0
            mostrar_panel(nombre)
            return
        else:
            intentos += 1
            messagebox.showerror("Error", "Contraseña incorrecta")
    else:
        intentos += 1
        messagebox.showerror("Error", "Usuario no encontrado")
    if intentos >= 3:
        enviar_comando("ALARMA_ON")
        messagebox.showwarning("¡Alarma!", "Demasiados intentos fallidos")
        intentos = 0

def registrar(nombre, contrasena, repetir, lbl):
    if nombre == "":
        messagebox.showerror("Error", "El usuario no puede estar vacío")
    elif len(contrasena) < 4:
        messagebox.showerror("Error", "Contraseña mínimo 4 caracteres")
    elif contrasena != repetir:
        messagebox.showerror("Error", "Las contraseñas no coinciden")
    elif nombre in cargar_usuarios():
        messagebox.showerror("Error", "Ese usuario ya existe")
    else:
        messagebox.showinfo("Éxito", f"Usuario '{nombre}' listo.\nAhora coloca el dedo en el sensor.")

def registrar_huella(lbl, nombre, contrasena, repetir):
    global _datos_registro
    if nombre == "":
        messagebox.showerror("Error", "Ingresa el usuario primero")
        return
    if len(contrasena) < 4:
        messagebox.showerror("Error", "Contraseña mínimo 4 caracteres")
        return
    if contrasena != repetir:
        messagebox.showerror("Error", "Las contraseñas no coinciden")
        return
    if nombre in cargar_usuarios():
        messagebox.showerror("Error", "Ese usuario ya existe")
        return
    # Guardar temporalmente los datos mientras el Pico registra la huella
    _datos_registro = {
        "nombre":   nombre,
        "password": hashlib.sha256(contrasena.encode()).hexdigest()
    }
    enviar_comando("REGISTRAR_HUELLA")
    lbl.config(text="☛ Esperando huella...",
               fg=paleta_de_colores["accent2"])

# ── PANEL ──────────────────────────────
def mostrar_panel(nombre):
    global _temp_var, _lbl_alarma
    for w in ventana.winfo_children():
        w.destroy()

    barra = tk.Frame(ventana, bg=paleta_de_colores["panel"],
                     highlightthickness=1,
                     highlightbackground=paleta_de_colores["border"],
                     padx=12, pady=8)
    barra.pack(fill="x")

    tk.Label(barra, text="⌂  HOGAR AUTOMÁTICO",
             font=("Consolas", 14, "bold"),
             fg=paleta_de_colores["accent"],
             bg=paleta_de_colores["panel"]).pack(side="left")

    _temp_var = tk.StringVar(value="🌡 -- °C")
    tk.Label(barra, textvariable=_temp_var,
             font=("Consolas", 12, "bold"),
             fg=paleta_de_colores["warning"],
             bg=paleta_de_colores["panel"]).pack(side="right", padx=16)

    tk.Label(barra, text=f"👤 {nombre}",
             font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["panel"]).pack(side="right", padx=12)

    tk.Button(barra, text="Cerrar Sesión",
              font=("Consolas", 9, "bold"),
              bg=paleta_de_colores["danger"],
              fg="white", relief="flat",
              cursor="hand2", padx=10, pady=4,
              command=mostrar_login).pack(side="right")

    lbl_conn = tk.Label(barra, text="● Desconectado",
                        font=("Consolas", 9),
                        fg=paleta_de_colores["danger"],
                        bg=paleta_de_colores["panel"])
    lbl_conn.pack(side="left", padx=8)

    def conectar():
        global puerto_serial
        try:
            puerto = encontrar_puerto_pico()
            if puerto:
                puerto_serial = serial.Serial(puerto, BAUD, timeout=1)
                lbl_conn.config(text=f"● {puerto}",
                                fg=paleta_de_colores["on"])
            else:
                lbl_conn.config(text="● No encontrado",
                                fg=paleta_de_colores["danger"])
        except Exception:
            lbl_conn.config(text="● Error",
                            fg=paleta_de_colores["danger"])

    tk.Button(barra, text="Conectar",
              font=("Consolas", 9, "bold"),
              bg=paleta_de_colores["on"],
              fg="white", relief="flat",
              cursor="hand2", padx=8,
              command=conectar).pack(side="left", padx=4)

    if puerto_serial and puerto_serial.is_open:
        lbl_conn.config(text="● Conectado", fg=paleta_de_colores["on"])

    cuerpo = tk.Frame(ventana, bg=paleta_de_colores["bg"])
    cuerpo.pack(fill="both", expand=True, padx=16, pady=12)

    sec_luces = tk.Frame(cuerpo, bg=paleta_de_colores["card"],
                         highlightthickness=1,
                         highlightbackground=paleta_de_colores["border"],
                         padx=12, pady=10)
    sec_luces.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    tk.Label(sec_luces, text="ILUMINACIÓN",
             font=("Consolas", 9, "bold"),
             fg=paleta_de_colores["accent"],
             bg=paleta_de_colores["card"]).pack(anchor="w", pady=(0, 10))

    luces = [
        ("💡 Sala",         "LUZ_SALA"),
        ("💡 Patio",        "LUZ_PATIO"),
        ("💡 Habitación 1", "LUZ_HAB1"),
        ("💡 Habitación 2", "LUZ_HAB2"),
        ("💡 Habitación 3", "LUZ_HAB3"),
        ("💡 Baño 1",       "LUZ_BANIO1"),
        ("💡 Baño 2",       "LUZ_BANIO2"),
        ("💡 Cocina",       "LUZ_COCINA"),
        ("💡 Pasillo",      "LUZ_PASILLO"),
    ]
    for nombre_luz, cmd in luces:
        fila = tk.Frame(sec_luces, bg=paleta_de_colores["card"])
        fila.pack(fill="x", pady=3)
        tk.Label(fila, text=nombre_luz,
                 font=("Consolas", 10),
                 fg=paleta_de_colores["text"],
                 bg=paleta_de_colores["card"],
                 width=16, anchor="w").pack(side="left")
        tk.Button(fila, text="ON",
                  font=("Consolas", 9, "bold"),
                  bg=paleta_de_colores["on"],
                  fg="white", relief="flat",
                  cursor="hand2", padx=8,
                  command=lambda c=cmd: enviar_comando(c + "_ON")
                  ).pack(side="left", padx=(0, 4))
        tk.Button(fila, text="OFF",
                  font=("Consolas", 9, "bold"),
                  bg=paleta_de_colores["border"],
                  fg="white", relief="flat",
                  cursor="hand2", padx=8,
                  command=lambda c=cmd: enviar_comando(c + "_OFF")
                  ).pack(side="left")

    sec_controles = tk.Frame(cuerpo, bg=paleta_de_colores["card"],
                             highlightthickness=1,
                             highlightbackground=paleta_de_colores["border"],
                             padx=12, pady=10)
    sec_controles.grid(row=0, column=1, sticky="nsew")
    tk.Label(sec_controles, text="CONTROLES",
             font=("Consolas", 9, "bold"),
             fg=paleta_de_colores["accent"],
             bg=paleta_de_colores["card"]).pack(anchor="w", pady=(0, 10))

    controles = [
        ("🪟 Cortinas", "CORTINA_ABRIR",  "CORTINA_CERRAR", "Abrir",    "Cerrar"),
        ("💧 Agua",     "AGUA_ON",        "AGUA_OFF",       "ON",       "OFF"),
        ("❄️  Aire",     "AIRE_ON",        "AIRE_OFF",       "ON",       "OFF"),
        ("🚪 Puerta",   "PUERTA_ABRIR",   "PUERTA_CERRAR",  "Abrir",    "Cerrar"),
    ]
    for nombre_ctrl, cmd_on, cmd_off, txt_on, txt_off in controles:
        fila = tk.Frame(sec_controles, bg=paleta_de_colores["card"])
        fila.pack(fill="x", pady=3)
        tk.Label(fila, text=nombre_ctrl,
                 font=("Consolas", 10),
                 fg=paleta_de_colores["text"],
                 bg=paleta_de_colores["card"],
                 width=14, anchor="w").pack(side="left")
        tk.Button(fila, text=txt_on,
                  font=("Consolas", 9, "bold"),
                  bg=paleta_de_colores["on"],
                  fg="white", relief="flat",
                  cursor="hand2", padx=8,
                  command=lambda c=cmd_on: enviar_comando(c)
                  ).pack(side="left", padx=(0, 4))
        tk.Button(fila, text=txt_off,
                  font=("Consolas", 9, "bold"),
                  bg=paleta_de_colores["danger"],
                  fg="white", relief="flat",
                  cursor="hand2", padx=8,
                  command=lambda c=cmd_off: enviar_comando(c)
                  ).pack(side="left")

    sec_alarma = tk.Frame(cuerpo, bg=paleta_de_colores["card"],
                          highlightthickness=1,
                          highlightbackground=paleta_de_colores["border"],
                          padx=12, pady=10)
    sec_alarma.grid(row=1, column=1, sticky="nsew", pady=(8, 0))
    tk.Label(sec_alarma, text="SEGURIDAD",
             font=("Consolas", 9, "bold"),
             fg=paleta_de_colores["accent"],
             bg=paleta_de_colores["card"]).pack(anchor="w", pady=(0, 10))

    _lbl_alarma = tk.Label(sec_alarma, text="● Sin movimiento",
                           font=("Consolas", 10, "bold"),
                           fg=paleta_de_colores["on"],
                           bg=paleta_de_colores["card"])
    _lbl_alarma.pack(pady=4)

    tk.Button(sec_alarma, text="🔕  Desactivar Alarma",
              font=("Consolas", 10, "bold"),
              bg=paleta_de_colores["danger"],
              fg="white", relief="flat",
              cursor="hand2", padx=10, pady=6,
              command=lambda: [
                  _lbl_alarma.config(text="● Sin movimiento",
                                     fg=paleta_de_colores["on"]),
                  enviar_comando("ALARMA_OFF")]
              ).pack(fill="x", pady=4)

    cuerpo.columnconfigure(0, weight=1)
    cuerpo.columnconfigure(1, weight=1)

# ── REGISTRO ───────────────────────────
def mostrar_registro():
    global _lbl_huella
    for w in ventana.winfo_children():
        w.destroy()

    card = tk.Frame(ventana, bg=paleta_de_colores["card"],
                    highlightthickness=1,
                    highlightbackground=paleta_de_colores["border"],
                    padx=40, pady=30)
    card.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(card, text="⌂  HOGAR AUTOMÁTICO",
             font=("Consolas", 20, "bold"),
             fg=paleta_de_colores["accent"],
             bg=paleta_de_colores["card"]).pack(pady=(0, 4))
    tk.Label(card, text="Registrarse",
             font=("Consolas", 11),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(pady=(0, 20))

    tk.Label(card, text="Usuario", font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(anchor="w")
    e_usuario = tk.Entry(card, bg=paleta_de_colores["border"],
             fg=paleta_de_colores["text"],
             insertbackground=paleta_de_colores["accent"],
             font=("Consolas", 11), relief="flat", width=28)
    e_usuario.pack(pady=(2, 12), ipady=6)

    tk.Label(card, text="Contraseña", font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(anchor="w")
    e_contrasena = tk.Entry(card, bg=paleta_de_colores["border"],
             fg=paleta_de_colores["text"],
             insertbackground=paleta_de_colores["accent"],
             font=("Consolas", 11), relief="flat", width=28, show="●")
    e_contrasena.pack(pady=(2, 12), ipady=6)

    tk.Label(card, text="Repetir Contraseña", font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(anchor="w")
    e_repetir = tk.Entry(card, bg=paleta_de_colores["border"],
             fg=paleta_de_colores["text"],
             insertbackground=paleta_de_colores["accent"],
             font=("Consolas", 11), relief="flat", width=28, show="●")
    e_repetir.pack(pady=(2, 12), ipady=6)

    tk.Label(card, text="Huella Digital", font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(anchor="w")
    _lbl_huella = tk.Label(card, text="✖ No registrada",
                           font=("Consolas", 9),
                           fg=paleta_de_colores["danger"],
                           bg=paleta_de_colores["card"])
    _lbl_huella.pack(anchor="w", pady=(2, 4))

    tk.Button(card, text="☛  Colocar dedo en sensor",
              font=("Consolas", 9),
              bg=paleta_de_colores["accent2"],
              fg="white", relief="flat",
              cursor="hand2", padx=8, pady=4,
              command=lambda: registrar_huella(
                  _lbl_huella,
                  e_usuario.get(),
                  e_contrasena.get(),
                  e_repetir.get())
              ).pack(fill="x", pady=(0, 8))

    tk.Button(card, text="Registrarse",
              font=("Consolas", 10, "bold"),
              bg=paleta_de_colores["accent"],
              fg="white", relief="flat",
              cursor="hand2", padx=12, pady=6,
              command=lambda: registrar(
                  e_usuario.get(),
                  e_contrasena.get(),
                  e_repetir.get(),
                  _lbl_huella)
              ).pack(fill="x", pady=(8, 4))

    tk.Button(card, text="¿Ya tienes cuenta? Inicia Sesión",
              font=("Consolas", 9),
              fg=paleta_de_colores["accent"],
              bg=paleta_de_colores["card"],
              bd=0, cursor="hand2",
              command=mostrar_login).pack()

# ── LOGIN ──────────────────────────────
def mostrar_login():
    global _lbl_huella
    for w in ventana.winfo_children():
        w.destroy()

    card = tk.Frame(ventana, bg=paleta_de_colores["card"],
                    highlightthickness=1,
                    highlightbackground=paleta_de_colores["border"],
                    padx=40, pady=30)
    card.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(card, text="⌂  HOGAR AUTOMÁTICO",
             font=("Consolas", 20, "bold"),
             fg=paleta_de_colores["accent"],
             bg=paleta_de_colores["card"]).pack(pady=(0, 4))
    tk.Label(card, text="Iniciar Sesión",
             font=("Consolas", 11),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(pady=(0, 20))

    tk.Label(card, text="Usuario", font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(anchor="w")
    e_usuario = tk.Entry(card, bg=paleta_de_colores["border"],
             fg=paleta_de_colores["text"],
             insertbackground=paleta_de_colores["accent"],
             font=("Consolas", 11), relief="flat", width=28)
    e_usuario.pack(pady=(2, 12), ipady=6)

    tk.Label(card, text="Contraseña", font=("Consolas", 10),
             fg=paleta_de_colores["muted"],
             bg=paleta_de_colores["card"]).pack(anchor="w")
    e_contrasena = tk.Entry(card, bg=paleta_de_colores["border"],
             fg=paleta_de_colores["text"],
             insertbackground=paleta_de_colores["accent"],
             font=("Consolas", 11), relief="flat", width=28, show="●")
    e_contrasena.pack(pady=(2, 12), ipady=6)

    _lbl_huella = tk.Label(card, text="",
                           font=("Consolas", 9),
                           fg=paleta_de_colores["accent2"],
                           bg=paleta_de_colores["card"])
    _lbl_huella.pack()

    tk.Button(card, text="☛  Iniciar sesión con huella",
              font=("Consolas", 9),
              bg=paleta_de_colores["accent2"],
              fg="white", relief="flat",
              cursor="hand2", padx=8, pady=4,
              command=lambda: [
                  _lbl_huella.config(text="☛ Coloque el dedo...",
                                     fg=paleta_de_colores["accent2"]),
                  enviar_comando("LEER_HUELLA")]
              ).pack(fill="x", pady=(4, 8))

    tk.Button(card, text="Iniciar Sesión",
              font=("Consolas", 10, "bold"),
              bg=paleta_de_colores["accent"],
              fg="white", relief="flat",
              cursor="hand2", padx=12, pady=6,
              command=lambda: verificar_login(e_usuario.get(),
                                             e_contrasena.get())
              ).pack(fill="x", pady=(0, 4))

    tk.Button(card, text="¿No tienes cuenta? Regístrate",
              font=("Consolas", 9),
              fg=paleta_de_colores["accent"],
              bg=paleta_de_colores["card"],
              bd=0, cursor="hand2",
              command=mostrar_registro).pack()

# ── INICIO ─────────────────────────────
conectar_automatico()
iniciar_hilo_lectura()
mostrar_login()
ventana.mainloop()