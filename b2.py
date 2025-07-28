import os
import json
import time
import random
import spidev
from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

VERSION = "1.1"

# --- LCD ---
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
selection = 0   # 0 až 7 (4 buňky na řádku × 2 řádky)
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
    # Vrací název pole a hodnotu podle indexu selection (0-7)
    if idx == 0:
        return "active", "On" if ch['active'] else "Off"
    if idx == 1:
        return "playFix", "Fix" if ch['playFix'] else "Rand"
    if idx == 2:
        return "playEvery", f"{playOptions[ch['playEvery']]:.1f}"
    if idx == 3:
        return "playPosition", f"{playOptions[ch['playPosition']]:.1f}"
    if idx == 4:
        return "channelVolume", str(ch['channelVolume'])
    if idx == 5:
        return "hitThreshold", str(ch['hitThreshold'])
    if idx == 6:
        return "releaseThreshold", str(ch['releaseThreshold'])
    if idx == 7:
        return "debounce", str(ch['debounce'])

def set_field_value(ch, idx, up=True):
    # Mění hodnotu podle typu pole a směru (+/-)
    if idx == 0:
        ch['active'] = not ch['active']
    elif idx == 1:
        ch['playFix'] = not ch['playFix']
    elif idx == 2:
        ch['playEvery'] = min(max(ch['playEvery'] + (1 if up else -1), 0), len(playOptions)-1)
    elif idx == 3:
        ch['playPosition'] = min(max(ch['playPosition'] + (1 if up else -1), 0), len(playOptions)-1)
    elif idx == 4:
        step = 1
        ch['channelVolume'] = min(max(ch['channelVolume'] + (step if up else -step),1),10)
    elif idx == 5:
        step = 10
        ch['hitThreshold'] = min(max(ch['hitThreshold'] + (step if up else -step),0),100)
    elif idx == 6:
        step = 10
        ch['releaseThreshold'] = min(max(ch['releaseThreshold'] + (step if up else -step),0),ch['hitThreshold'])
    elif idx == 7:
        step = 10
        ch['debounce'] = min(max(ch['debounce'] + (step if up else -step),0),9999)

# --- Zobrazení na LCD ---
def show_big(selection=0, editMode=False, blinkState=True):
    ch = preset[currentPreset][currentChannel]
    # První dva řádky: název samplu (bez .wav), rozděleno na dvě buňky po deseti znacích
    name = ch['sound']
    lcd_big.cursor_mode = 'hide'
    lcd_big.cursor_pos = (0,0)
    lcd_big.write_string(("*"+name[:9]).ljust(10))
    lcd_big.cursor_pos = (0,10)
    lcd_big.write_string(("*"+name[9:18]).ljust(10))

    # Třetí řádek: čtyři buňky po pěti znacích
    row3_fields = []
    for i in range(4):
        field, value = get_field_and_value(ch,i)
        prefix = "*" if not (selection==i and not editMode) else " "
        # Pokud je editMode a selection==i a blinkState==False, zobraz prázdno místo hodnoty (blikání)
        disp_val = value if not (selection==i and editMode and not blinkState) else "     "
        row3_fields.append(prefix + disp_val.rjust(4))
    lcd_big.cursor_pos = (2,0)
    lcd_big.write_string("".join(row3_fields))

    # Čtvrtý řádek: další čtyři buňky po pěti znacích
    row4_fields = []
    for i in range(4,8):
        field, value = get_field_and_value(ch,i)
        prefix = "*" if not (selection==i and not editMode) else " "
        disp_val = value if not (selection==i and editMode and not blinkState) else "     "
        row4_fields.append(prefix + disp_val.rjust(4))
    lcd_big.cursor_pos = (3,0)
    lcd_big.write_string("".join(row4_fields))

    # Nastav kurzor na začátek vybrané buňky
    row_idx = 2 if selection <4 else 3
    col_idx = (selection%4)*5
    lcd_big.cursor_pos=(row_idx,col_idx)
    if editMode:
        lcd_big.cursor_mode='blink'
    else:
        lcd_big.cursor_mode='line'

# --- Hlavní smyčka ---
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

        # Ovládání tlačítek pro pohyb mezi buňkami
        if GPIO.input(BUTTON_LEFT) == GPIO.LOW and not editMode:
            selection -=1
            if selection<0: selection=7
            show_big(selection, editMode, editBlinkState)
            time.sleep(0.2)

        if GPIO.input(BUTTON_RIGHT) == GPIO.LOW and not editMode:
            selection +=1
            if selection>7: selection=0
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
    lcd_big.clear()
    GPIO.cleanup()
