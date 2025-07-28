import os
import json
import time
import random
import spidev
from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

VERSION = "1.0"

# --- Nastavení LCD ---
lcd_small = CharLCD('PCF8574', 0x26, cols=16, rows=2)
lcd_big = CharLCD('PCF8574', 0x27, cols=20, rows=4)

# --- Nastavení SPI pro MCP3208 (CS0 = GPIO8) ---
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000

# --- GPIO tlačítka ---
BUTTON_EDIT = 17
BUTTON_LEFT = 27
BUTTON_RIGHT = 22
BUTTON_UP = 23
BUTTON_DOWN = 24
BUTTON_NEXT_PRESET = 19
BUTTON_RESET = 26

GPIO.setmode(GPIO.BCM)
for pin in [BUTTON_EDIT, BUTTON_LEFT, BUTTON_RIGHT, BUTTON_UP, BUTTON_DOWN, BUTTON_NEXT_PRESET, BUTTON_RESET]:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- Načtení samplů z SD/USB ---
def loadSamplesFromSD(path="/volumes/ZVUKY/"):
    samples = ["Empty"]
    try:
        for fname in os.listdir(path):
            if fname.lower().endswith(".wav"):
                samples.append(fname[:-4])
    except Exception:
        pass
    return samples

samples = loadSamplesFromSD()

# --- Globální proměnné a preset struktura ---
NUM_PRESETS = 8
NUM_CHANNELS = 8
playOptions = [1 + 0.5 * i for i in range(64)]  # 1, 1.5, ..., 32.5

preset = [
    [
        {
            'active': True,
            'sound': 'Empty',
            'velocity': 0,
            'hitCount': 0,
            'barCount': 0,
            'playFix': True,
            'playEvery': 0,
            'playPosition': 0,
            'randomFrom': 0,
            'randomTo': 1,
            'channelVolume': 10,
            'hitThreshold': 60,
            'releaseThreshold': 59,
            'debounce': 50,
            'last_hit_time': 0,
            'armed': True
        }
        for _ in range(NUM_CHANNELS)
    ] for _ in range(NUM_PRESETS)
]

currentPreset = 0
currentChannel = 0
selection = 0   # 0 až 8 (viz pole níže)
editMode = False
editBlinkState = True
editLastBlink = time.time()
BLINK_INTERVAL = 0.4

# --- JSON Ukládání/načítání ---
def saveShitToJSON():
    with open("presets.json", "w") as f:
        json.dump(preset, f)

def loadShitFromJSON():
    global preset
    try:
        with open("presets.json", "r") as f:
            preset = json.load(f)
    except Exception:
        pass

# --- Čtení kanálu z MCP3208 ---
def read_channel(channel):
    adc = spi.xfer2([6 | (channel >> 2), (channel & 3) << 6, 0])
    data = ((adc[1] & 15) << 8) | adc[2]
    return data

# --- Výběr pole pro editaci (indexy odpovídají selection) ---
def get_edit_fields(ch):
    return [
        ch['active'],
        ch['playFix'],
        ch['playEvery'],
        ch['playPosition'],
        ch['channelVolume'],
        ch['hitThreshold'],
        ch['releaseThreshold'],
        ch['debounce'],
        ch['sound']
    ]

def set_edit_field(ch, idx, value):
    if idx == 0:
        ch['active'] = value
    elif idx == 1:
        ch['playFix'] = value
    elif idx == 2:
        ch['playEvery'] = value
    elif idx == 3:
        ch['playPosition'] = value
    elif idx == 4:
        ch['channelVolume'] = value
    elif idx == 5:
        ch['hitThreshold'] = value
    elif idx == 6:
        ch['releaseThreshold'] = value
    elif idx == 7:
        ch['debounce'] = value
    elif idx == 8:
        ch['sound'] = value

# --- Zobrazení na LCD ---
def show_small():
    lcd_small.cursor_pos = (0, 0)
    lcd_small.write_string(f"PR {currentPreset+1:02d}   CH {currentChannel+1:02d}   ")
    lcd_small.cursor_pos = (1, 0)
    lcd_small.write_string(
        f"{preset[currentPreset][currentChannel]['barCount']:04d}    "
        f"{preset[currentPreset][currentChannel]['velocity']:04d}    "
    )

def show_big(selection=None, editMode=False):
    ch = preset[currentPreset][currentChannel]
    name = ch['sound']
    lcd_big.cursor_pos = (0, 0)
    lcd_big.write_string(name[:20].ljust(20))
    lcd_big.cursor_pos = (1, 0)
    lcd_big.write_string(name[20:40].ljust(20) if len(name) > 20 else " " * 20)

    # Třetí řádek: čtyři pole po pěti znacích s případným zvýrazněním selection pomlčkou
    fields3 = [
        ("-" if selection==1 and editMode and editBlinkState else "") + ("On" if ch['active'] else "Off").ljust(4),
        ("-" if selection==2 and editMode and editBlinkState else "") + ("Fix" if ch['playFix'] else "Rand").ljust(4),
        ("-" if selection==3 and editMode and editBlinkState else "") + (
            f"{playOptions[ch['playEvery']]:>4}" if ch['playFix'] else f"{playOptions[ch['randomFrom']]:>4}"
        ),
        ("-" if selection==4 and editMode and editBlinkState else "") + (
            f"{playOptions[ch['playPosition']]:>4}" if ch['playFix'] else f"{playOptions[ch['randomTo']]:>4}"
        )
    ]
    row3 = "".join(fields3)
    lcd_big.cursor_pos = (2, 0)
    lcd_big.write_string(row3[:20])

    # Čtvrtý řádek: volume, hitThreshold, releaseThreshold, debounce s případným zvýrazněním selection pomlčkou
    fields4 = [
        ("-" if selection==5 and editMode and editBlinkState else "") + f"{ch['channelVolume']:>4}",
        ("-" if selection==6 and editMode and editBlinkState else "") + f"{ch['hitThreshold']:>4}",
        ("-" if selection==7 and editMode and editBlinkState else "") + f"{ch['releaseThreshold']:>4}",
        ("-" if selection==8 and editMode and editBlinkState else "") + f"{ch['debounce']:>4}"
    ]
    row4 = "".join(fields4)
    lcd_big.cursor_pos = (3, 0)
    lcd_big.write_string(row4[:20])

# --- Hlavní smyčka ---
show_small()
show_big(selection, editMode)

try:
    while True:
        # Blikání v editMode pro zvýraznění hodnoty pomlčkou
        if editMode:
            now_blink = time.time()
            if now_blink - editLastBlink > BLINK_INTERVAL:
                editBlinkState = not editBlinkState
                editLastBlink = now_blink
                show_big(selection, editMode)

        # Čtení správného kanálu z MCP3208
        val = read_channel(currentChannel)
        velocity = int((val / 4095) * 100)
        now = time.time()

        ch = preset[currentPreset][currentChannel]
        # Detekce úderu s thresholdy a debounce
        if ch['armed'] and val > ch['hitThreshold']:
            if (now - ch['last_hit_time']) * 1000 > ch['debounce']:
                ch['hitCount'] += 1
                ch['barCount'] += 1
                ch['velocity'] = velocity
                ch['last_hit_time'] = now
                ch['armed'] = False
                show_small()
                show_big(selection, editMode)
        if not ch['armed'] and val < ch['releaseThreshold']:
            ch['armed'] = True

        # --- Ovládání tlačítek ---
        if GPIO.input(BUTTON_LEFT) == GPIO.LOW:
            selection -= 1
            if selection < 1:
                selection = 8
            show_big(selection, editMode)
            time.sleep(0.2)

        if GPIO.input(BUTTON_RIGHT) == GPIO.LOW:
            selection += 1
            if selection > 8:
                selection = 1
            show_big(selection, editMode)
            time.sleep(0.2)

        # Edit mode toggle a změna hodnoty v editaci
        if GPIO.input(BUTTON_EDIT) == GPIO.LOW:
            if not editMode:
                editMode = True
                show_big(selection, editMode)
                time.sleep(0.2)
            else:
                saveShitToJSON()
                editMode = False
                show_big(selection, editMode)
                time.sleep(0.2)

        # Pokud jsme v editaci a stiskneme nahoru/dolu – měníme hodnotu podle typu pole
        if editMode:
            step_map_10s = [5,6,7,8] # indexy pro které listujeme po desítkách (thresholdy/debounce)
            step_map_samples = [9]   # pokud bys chtěl listovat samplem (zde není implementováno)
            step_size = 10 if selection in step_map_10s else 1

            if GPIO.input(BUTTON_UP) == GPIO.LOW:
                val_before = get_edit_fields(ch)[selection-1]
                # Přepínání hodnot podle typu pole (příklad pro čísla a bool)
                if isinstance(val_before, bool):
                    set_edit_field(ch, selection-1, not val_before)
                elif isinstance(val_before, int):
                    set_edit_field(ch, selection-1, val_before + step_size)
                show_big(selection, editMode)
                time.sleep(0.2)

            if GPIO.input(BUTTON_DOWN) == GPIO.LOW:
                val_before = get_edit_fields(ch)[selection-1]
                if isinstance(val_before, bool):
                    set_edit_field(ch, selection-1, not val_before)
                elif isinstance(val_before, int):
                    set_edit_field(ch, selection-1, max(0,val_before - step_size))
                show_big(selection, editMode)
                time.sleep(0.2)

        # Ostatní tlačítka jako dřív...
        if GPIO.input(BUTTON_UP) == GPIO.LOW and not editMode:
            currentChannel = (currentChannel + 1) % NUM_CHANNELS
            show_small()
            show_big(selection, editMode)
            time.sleep(0.2)

        if GPIO.input(BUTTON_DOWN) == GPIO.LOW and not editMode:
            currentChannel = (currentChannel - 1) % NUM_CHANNELS
            show_small()
            show_big(selection, editMode)
            time.sleep(0.2)

        if GPIO.input(BUTTON_NEXT_PRESET) == GPIO.LOW:
            currentPreset = (currentPreset + 1) % NUM_PRESETS
            show_small()
            show_big(selection, editMode)
            time.sleep(0.2)

        if GPIO.input(BUTTON_RESET) == GPIO.LOW:
            for p in range(NUM_PRESETS):
                for c in range(NUM_CHANNELS):
                    preset[p][c]['hitCount'] = 0
                    preset[p][c]['barCount'] = 0
                    preset[p][c]['velocity'] = 0
                    preset[p][c]['armed'] = True
            show_small()
            show_big(selection, editMode)
            time.sleep(0.2)

        time.sleep(0.01)

except KeyboardInterrupt:
    spi.close()
    lcd_small.clear()
    lcd_big.clear()
    GPIO.cleanup()
    print("Bye")
