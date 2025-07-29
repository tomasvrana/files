import os
import json
import time
import random
import spidev
from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

VERSION = "1.3"

# --- LCD ---
lcd_small = CharLCD('PCF8574', 0x26, cols=16, rows=2)
lcd_big = CharLCD('PCF8574', 0x27, cols=20, rows=4)

# --- SPI pro MCP3208 (CS0 = GPIO8) ---
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000

# --- GPIO tlačítka ---
BUTTON_EDIT = 17
BUTTON_LEFT = 27
BUTTON_RIGHT = 22
BUTTON_UP = 23
BUTTON_DOWN = 24

GPIO.setmode(GPIO.BCM)
for pin in [BUTTON_EDIT, BUTTON_LEFT, BUTTON_RIGHT, BUTTON_UP, BUTTON_DOWN]:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- Načtení samplů z USB/SD ---
def loadSamplesFromSD(path="/media/tom/ZVUKY1/"):
    samples = ["Empty"]
    try:
        for fname in os.listdir(path):
            # Ignoruj skryté soubory a ty s prefixem ._
            if fname.startswith('.') or fname.startswith('._'):
                continue
            if fname.lower().endswith(".wav"):
                samples.append(fname[:-4])
        if len(samples) == 1:
            return ["Card Error!"]
        return samples
    except Exception as e:
        print("Chyba při čtení složky:", e)
        return ["Card Error!"]

samples = loadSamplesFromSD()
print("Loaded samples:", samples)

# --- Globální proměnné a preset struktura ---
NUM_PRESETS = 8
NUM_CHANNELS = 8
playOptions = [1 + 0.5 * i for i in range(64)]  # 1, 1.5, ..., 32.5

preset = [
    [
        {
            'active': True,
            'sound': samples[0],
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
selection = 0   # 0 až 8 (sample + 4+4 buněk)
editMode = False
editBlinkState = True
editLastBlink = time.time()
BLINK_INTERVAL = 0.4

# --- Čtení kanálu z MCP3208 ---
def read_channel(channel):
    adc = spi.xfer2([6 | (channel >> 2), (channel & 3) << 6, 0])
    data = ((adc[1] & 15) << 8) | adc[2]
    return data

# --- Pomocné funkce pro editaci ---
def get_field_and_value(ch, idx):
    if idx == 0:
        return "sound", ch['sound']
    if idx == 1:
        return "active", "On" if ch['active'] else "Off"
    if idx == 2:
        return "playFix", "Fix" if ch['playFix'] else "Ran"
    if idx == 3:
        return "playEvery", f"{playOptions[ch['playEvery']]:.1f}"
    if idx == 4:
        return "playPosition", f"{playOptions[ch['playPosition']]:.1f}"
    if idx == 5:
        return "channelVolume", str(ch['channelVolume'])
    if idx == 6:
        return "hitThreshold", str(ch['hitThreshold'])
    if idx == 7:
        return "releaseThreshold", str(ch['releaseThreshold'])
    if idx == 8:
        return "debounce", str(ch['debounce'])

def set_field_value(ch, idx, up=True):
    if idx == 0: # sample výběr
        cur_idx = samples.index(ch['sound']) if ch['sound'] in samples else 0
        if up:
            cur_idx = (cur_idx + 1) % len(samples)
        else:
            cur_idx = (cur_idx - 1) % len(samples)
        ch['sound'] = samples[cur_idx]
    elif idx == 1:
        ch['active'] = not ch['active']
    elif idx == 2:
        ch['playFix'] = not ch['playFix']
    elif idx == 3:
        ch['playEvery'] = min(max(ch['playEvery'] + (1 if up else -1), 0), len(playOptions)-1)
    elif idx == 4:
        ch['playPosition'] = min(max(ch['playPosition'] + (1 if up else -1), 0), len(playOptions)-1)
    elif idx == 5:
        step = 1
        ch['channelVolume'] = min(max(ch['channelVolume'] + (step if up else -step),1),10)
    elif idx == 6:
        step = 10
        ch['hitThreshold'] = min(max(ch['hitThreshold'] + (step if up else -step),0),100)
    elif idx == 7:
        step = 10
        ch['releaseThreshold'] = min(max(ch['releaseThreshold'] + (step if up else -step),0),ch['hitThreshold'])
    elif idx == 8:
        step = 10
        ch['debounce'] = min(max(ch['debounce'] + (step if up else -step),0),9999)

# --- Malý displej ---
def show_small():
    lcd_small.cursor_pos = (0, 0)
    lcd_small.write_string(f"PR {currentPreset+1:02d}   CH {currentChannel+1:02d}   ")
    lcd_small.cursor_pos = (1, 0)
    lcd_small.write_string(
        f"{preset[currentPreset][currentChannel]['barCount']:04d}    "
        f"{preset[currentPreset][currentChannel]['velocity']:04d}    "
    )

# --- Velký displej ---
def show_big(selection=0, editMode=False, blinkState=True):
    ch = preset[currentPreset][currentChannel]
    lcd_big.cursor_mode = 'hide'

    # První dva řádky: název samplu s prefixem jen na začátku prvního řádku
    name = ch['sound']
    prefix_char = "-" if selection==0 and not editMode else "*"
    disp_name = name if not (selection==0 and editMode and not blinkState) else ""
    lcd_big.cursor_pos = (0,0)
    lcd_big.write_string((prefix_char + disp_name[:19]).ljust(20))
    lcd_big.cursor_pos = (1,0)
    lcd_big.write_string((" " + disp_name[19:39]).ljust(20) if len(disp_name)>19 else " "*20)

    # Třetí řádek: čtyři buňky po pěti znacích, zarovnáno doleva bez mezery za prefixem
    row3_fields = []
    for i in range(1,5):
        field, value = get_field_and_value(ch,i)
        prefix = "-" if selection==i and not editMode else "*"
        disp_val = value if not (selection==i and editMode and not blinkState) else ""
        row3_fields.append(prefix + disp_val.ljust(4))
    lcd_big.cursor_pos = (2,0)
    lcd_big.write_string("".join(row3_fields))

    # Čtvrtý řádek: další čtyři buňky po pěti znacích
    row4_fields = []
    for i in range(5,9):
        field, value = get_field_and_value(ch,i)
        prefix = "-" if selection==i and not editMode else "*"
        disp_val = value if not (selection==i and editMode and not blinkState) else ""
        row4_fields.append(prefix + disp_val.ljust(4))
    lcd_big.cursor_pos = (3,0)
    lcd_big.write_string("".join(row4_fields))

    # Nastav kurzor na začátek vybrané buňky
    if selection==0:
        lcd_big.cursor_pos=(0,0)
    elif selection<5:
        lcd_big.cursor_pos=(2,(selection-1)*5)
    else:
        lcd_big.cursor_pos=(3,(selection-5)*5)
    if editMode:
        lcd_big.cursor_mode='blink'
    else:
        lcd_big.cursor_mode='line'

# --- Hlavní smyčka ---
show_small()
show_big(selection, editMode, editBlinkState)

try:
    while True:
        # Blikání v editMode pro zvýraznění hodnoty v buňce
        if editMode:
            now_blink = time.time()
            if now_blink - editLastBlink > BLINK_INTERVAL:
                editBlinkState = not editBlinkState
                editLastBlink = now_blink
                show_big(selection, editMode, editBlinkState)

        # Čtení správného kanálu z MCP3208 a update malého displeje
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
                show_big(selection, editMode, editBlinkState)
        if not ch['armed'] and val < ch['releaseThreshold']:
            ch['armed'] = True

        # Ovládání tlačítek pro pohyb mezi buňkami
        if GPIO.input(BUTTON_LEFT) == GPIO.LOW and not editMode:
            selection -=1
            if selection<0: selection=8
            show_big(selection, editMode, editBlinkState)
            time.sleep(0.2)

        if GPIO.input(BUTTON_RIGHT) == GPIO.LOW and not editMode:
            selection +=1
            if selection>8: selection=0
            show_big(selection, editMode, editBlinkState)
            time.sleep(0.2)

        # Edit mode toggle a změna hodnoty v editaci
        if GPIO.input(BUTTON_EDIT) == GPIO.LOW:
            if not editMode:
                editMode=True
                show_big(selection, editMode, editBlinkState)
                time.sleep(0.2)
            else:
                # Uložení změny a vypnutí blikání kurzoru
                editMode=False
                show_big(selection, editMode, True)
                time.sleep(0.2)

        # Pokud jsme v editaci a stiskneme nahoru/dolu – měníme hodnotu v aktivní buňce
        if editMode:
            if GPIO.input(BUTTON_UP) == GPIO.LOW:
                set_field_value(preset[currentPreset][currentChannel], selection, up=True)
                show_big(selection, editMode, True)
                time.sleep(0.2)
            if GPIO.input(BUTTON_DOWN) == GPIO.LOW:
                set_field_value(preset[currentPreset][currentChannel], selection, up=False)
                show_big(selection, editMode, True)
                time.sleep(0.2)

except KeyboardInterrupt:
    spi.close()
    lcd_small.clear()
    lcd_big.clear()
    GPIO.cleanup()
