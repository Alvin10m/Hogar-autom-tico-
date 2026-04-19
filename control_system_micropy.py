import sys
import json
import time
import math
from machine import Pin, ADC, UART, PWM
import uselect

PINES = {
    "LUZ_SALA":     Pin(0,  Pin.OUT),
    "LUZ_PATIO":    Pin(1,  Pin.OUT),
    "LUZ_HAB1":     Pin(2,  Pin.OUT),
    "LUZ_HAB2":     Pin(3,  Pin.OUT),
    "LUZ_HAB3":     Pin(4,  Pin.OUT),
    "LUZ_BANIO1":   Pin(5,  Pin.OUT),
    "LUZ_BANIO2":   Pin(6,  Pin.OUT),
    "LUZ_COCINA":   Pin(7,  Pin.OUT),
    "LUZ_PASILLO":  Pin(8,  Pin.OUT),
    "RELE_CORTINA": Pin(9,  Pin.OUT),
    "AGUA":         Pin(11, Pin.OUT),
    "AIRE":         Pin(12, Pin.OUT),
    "RELE_PUERTA":  Pin(13, Pin.OUT),
}

buzzer      = PWM(Pin(15))
sensor_temp = ADC(26)
fotoresist  = ADC(27)
infrarrojo  = Pin(19, Pin.IN, Pin.PULL_UP)
pir         = Pin(22, Pin.IN, Pin.PULL_DOWN)
huella_uart = UART(1, baudrate=57600, tx=Pin(20), rx=Pin(21))

alarma_activa        = False
modo_automatico_aire = True
estado_aire          = False
estado_luz_patio     = False
estado_cortina       = None
proximo_id_huella    = 1

# ── INICIALIZAR ────────────────────────
for nombre in ["LUZ_SALA","LUZ_PATIO","LUZ_HAB1","LUZ_HAB2","LUZ_HAB3",
               "LUZ_BANIO1","LUZ_BANIO2","LUZ_COCINA","LUZ_PASILLO"]:
    PINES[nombre].value(0)
for nombre in ["RELE_CORTINA","AGUA","AIRE","RELE_PUERTA"]:
    PINES[nombre].value(1)

# ── LEDS ───────────────────────────────
def led_on(nombre):  PINES[nombre].value(1)
def led_off(nombre): PINES[nombre].value(0)

# ── RELÉS ──────────────────────────────
def rele_on(pin):  pin.value(0)
def rele_off(pin): pin.value(1)

# ── BUZZER ─────────────────────────────
def buzzer_on():
    buzzer.freq(2000)
    buzzer.duty_u16(30000)

def buzzer_off():
    buzzer.duty_u16(0)

# ── TEMPERATURA ────────────────────────
def leer_temperatura():
    raw = sensor_temp.read_u16()
    if raw == 0:
        return 0.0
    r = (65535 / raw - 1) * 10000
    temp = 1 / (math.log(r / 10000) / 3950 + 1 / 298.15)
    return round(temp - 273.15 + 12, 1)

# ── FOTORESISTENCIA ────────────────────
def leer_luz():
    return fotoresist.read_u16() < 40000

# ── MOTORES ────────────────────────────
def activar_cortina():
    global estado_cortina
    if estado_cortina == "ON":
        return
    estado_cortina = "ON"
    rele_on(PINES["RELE_CORTINA"])
    time.sleep(3)
    rele_off(PINES["RELE_CORTINA"])
    estado_cortina = "OFF"

def activar_puerta():
    rele_on(PINES["RELE_PUERTA"])
    time.sleep(1.4)
    rele_off(PINES["RELE_PUERTA"])


# ── HUELLA AS608 ───────────────────────

def enviar_paquete_huella(cmd_bytes):
    huella_uart.write(cmd_bytes)


def leer_respuesta(timeout=10):
    inicio = time.time()
    data = b""

    while time.time() - inicio < timeout:
        if huella_uart.any():
            chunk = huella_uart.read()
            if chunk:
                data += chunk
        time.sleep(0.03)

    return data


# ✔️ VALIDACIÓN REAL AS608
def es_ok(resp):
    if not resp or len(resp) < 10:
        return False

    # header del AS608
    if resp[0] != 0xEF or resp[1] != 0x01:
        return False

    # byte de confirmación típico del módulo
    return resp[9] == 0x00



# ── ENVÍO ─────────────────────────────

def enviar_paquete_huella(cmd_bytes):
    huella_uart.write(cmd_bytes)


# ── LECTURA UART MÁS ESTABLE ──────────

def leer_respuesta(timeout=8):
    inicio = time.time()
    data = b""

    while time.time() - inicio < timeout:
        if huella_uart.any():
            chunk = huella_uart.read()
            if chunk:
                data += chunk
        time.sleep(0.02)

    return data


# ── VALIDACIÓN REALISTA AS608 ─────────

def es_ok(resp):
    if not resp or len(resp) < 10:
        return False

    if resp[0] != 0xEF or resp[1] != 0x01:
        return False

    return resp[9] == 0x00


# ── ESPERA INTELIGENTE DE DEDO ────────

def esperar_dedo(timeout=8):
    t = time.time()

    while time.time() - t < timeout:
        enviar_paquete_huella(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x03\x01\x00\x05'
        )

        time.sleep(1)

        resp = leer_respuesta(timeout=2)

        if resp and len(resp) > 10:
            return resp

    return None


# ──────────────────────────────────────
# LEER HUELLA (ABRIR PUERTA)
# ──────────────────────────────────────

def leer_huella():
    try:
        enviar("HUELLA_MSG", "Coloque el dedo")

        resp = esperar_dedo(10)

        if not resp:
            enviar("HUELLA_FAIL", 0)
            return

        enviar_paquete_huella(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x04\x02\x01\x00\x08'
        )

        time.sleep(1)
        resp = leer_respuesta(timeout=6)

        if not es_ok(resp):
            enviar("HUELLA_FAIL", 0)
            return

        enviar_paquete_huella(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x08\x04\x01\x00\x00\x00\xA3\x00\xB1'
        )

        time.sleep(1)
        resp = leer_respuesta(timeout=6)

        if es_ok(resp) and len(resp) >= 12:
            finger_id = resp[10]
            enviar("HUELLA_OK", finger_id)
            activar_puerta()
        else:
            enviar("HUELLA_FAIL", 0)

    except Exception:
        enviar("HUELLA_ERROR", "Error lectura")


# ──────────────────────────────────────
# REGISTRAR HUELLA
# ──────────────────────────────────────

def registrar_huella():
    global proximo_id_huella

    try:
        id_huella = proximo_id_huella

        enviar("HUELLA_MSG", "Coloque el dedo")

        resp = esperar_dedo(10)

        if not resp:
            enviar("HUELLA_ERROR", "No detectado")
            return

        enviar_paquete_huella(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x04\x02\x01\x00\x08'
        )

        time.sleep(1)
        resp = leer_respuesta(timeout=6)

        if not es_ok(resp):
            enviar("HUELLA_ERROR", "Error buffer 1")
            return

        enviar("HUELLA_MSG", "Retire el dedo")
        time.sleep(3)

        enviar("HUELLA_MSG", "Coloque el dedo otra vez")

        resp = esperar_dedo(10)

        if not resp:
            enviar("HUELLA_ERROR", "No detectado 2")
            return

        enviar_paquete_huella(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x04\x02\x02\x00\x09'
        )

        time.sleep(1)
        resp = leer_respuesta(timeout=6)

        if not es_ok(resp):
            enviar("HUELLA_ERROR", "Error buffer 2")
            return

        enviar_paquete_huella(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x03\x05\x00\x09'
        )

        time.sleep(1)
        resp = leer_respuesta(timeout=6)

        if not es_ok(resp):
            enviar("HUELLA_ERROR", "Error modelo")
            return

        # ── GUARDAR ──
        paquete = bytearray(
            b'\xEF\x01\xFF\xFF\xFF\xFF\x01\x00\x06\x06\x01\x00'
        )

        paquete.append(id_huella)
        paquete.append(0x00)

        checksum = sum(paquete[6:]) & 0xFFFF
        paquete.append((checksum >> 8) & 0xFF)
        paquete.append(checksum & 0xFF)

        enviar_paquete_huella(paquete)

        time.sleep(2)
        resp = leer_respuesta(timeout=8)

        if not es_ok(resp):
            enviar("HUELLA_ERROR", "Error guardando")
            return

        proximo_id_huella += 1
        enviar("HUELLA_REGISTRADA", id_huella)

    except Exception:
        enviar("HUELLA_ERROR", "Fallo registro")


# ── COMANDOS ───────────────────────────
def ejecutar(cmd):
    global alarma_activa, modo_automatico_aire, estado_aire

    mapa_luces = {
        "LUZ_SALA_ON":     ("LUZ_SALA",    True),
        "LUZ_SALA_OFF":    ("LUZ_SALA",    False),
        "LUZ_PATIO_ON":    ("LUZ_PATIO",   True),
        "LUZ_PATIO_OFF":   ("LUZ_PATIO",   False),
        "LUZ_HAB1_ON":     ("LUZ_HAB1",    True),
        "LUZ_HAB1_OFF":    ("LUZ_HAB1",    False),
        "LUZ_HAB2_ON":     ("LUZ_HAB2",    True),
        "LUZ_HAB2_OFF":    ("LUZ_HAB2",    False),
        "LUZ_HAB3_ON":     ("LUZ_HAB3",    True),
        "LUZ_HAB3_OFF":    ("LUZ_HAB3",    False),
        "LUZ_BANIO1_ON":   ("LUZ_BANIO1",  True),
        "LUZ_BANIO1_OFF":  ("LUZ_BANIO1",  False),
        "LUZ_BANIO2_ON":   ("LUZ_BANIO2",  True),
        "LUZ_BANIO2_OFF":  ("LUZ_BANIO2",  False),
        "LUZ_COCINA_ON":   ("LUZ_COCINA",  True),
        "LUZ_COCINA_OFF":  ("LUZ_COCINA",  False),
        "LUZ_PASILLO_ON":  ("LUZ_PASILLO", True),
        "LUZ_PASILLO_OFF": ("LUZ_PASILLO", False),
    }

    if cmd in mapa_luces:
        nombre, encender = mapa_luces[cmd]
        led_on(nombre) if encender else led_off(nombre)
    elif cmd == "AGUA_ON":
        rele_on(PINES["AGUA"])
    elif cmd == "AGUA_OFF":
        rele_off(PINES["AGUA"])
    elif cmd == "AIRE_ON":
        modo_automatico_aire = False
        rele_on(PINES["AIRE"])
        estado_aire = True
    elif cmd == "AIRE_OFF":
        modo_automatico_aire = False
        rele_off(PINES["AIRE"])
        estado_aire = False
    elif cmd == "ALARMA_ON":
        alarma_activa = True
        buzzer_on()
    elif cmd == "ALARMA_OFF":
        alarma_activa = False
        buzzer_off()
    elif cmd in ("CORTINA_ABRIR", "CORTINA_CERRAR"):
        activar_cortina()
    elif cmd in ("PUERTA_ABRIR", "PUERTA_CERRAR"):
        activar_puerta()
    elif cmd == "REGISTRAR_HUELLA":
        registrar_huella()
    elif cmd == "LEER_HUELLA":
        leer_huella()

# ── ENVIAR ─────────────────────────────
def enviar(evento, val):
    sys.stdout.write(json.dumps({"evento": evento, "val": val}) + "\n")

# ── BUCLE PRINCIPAL ────────────────────
poll = uselect.poll()
poll.register(sys.stdin, uselect.POLLIN)
tick = 0

while True:
    if poll.poll(0):
        linea = sys.stdin.readline().strip()
        if linea:
            try:
                ejecutar(json.loads(linea).get("cmd", ""))
            except Exception:
                pass

    tick += 1
    if tick >= 20:
        tick = 0
        temp = leer_temperatura()
        enviar("TEMPERATURA", float(temp))

        if modo_automatico_aire:
            if temp > 27:
                rele_on(PINES["AIRE"])
                estado_aire = True
            elif temp < 25:
                rele_off(PINES["AIRE"])
                estado_aire = False

        nueva_luz = leer_luz()
        if nueva_luz != estado_luz_patio:
            estado_luz_patio = nueva_luz
            if estado_luz_patio:
                led_off("LUZ_PATIO")
                enviar("LUZ_PATIO", "OFF")
            else:
                led_on("LUZ_PATIO")
                enviar("LUZ_PATIO", "ON")
            activar_cortina()

    if (pir.value() == 1 or infrarrojo.value() == 0) and not alarma_activa:
        alarma_activa = True
        buzzer_on()
        enviar("MOVIMIENTO", "area_restringida")

    time.sleep(0.1)