import os
import json
import time
import random
import spidev
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

# --- CONFIG ---
NUM_PRESETS = 8
NUM_CHANNELS = 8
playOptions = [1 + 0.5 * i for i in range(64)]  # 1, 1.5, ..., 32.5
SAMPLES_PATH = "/volumes/ZVUKY/"

# LCD addresses
LCD_SMALL_ADDR = 0x26  # 16x2
LCD_BIG_ADDR = 0x27    # 20x4

# GPIO pins
BUTTON_EDIT = 17
BUTTON_LEFT = 27
BUTTON_RIGHT = 22
BUTTON_UP = 23
BUTTON_DOWN = 24
BUTTON_NEXT_PRESET = 19
BUTTON_RESET = 26

# --- INIT ---
GPIO.setmode(GPIO.BCM)
for pin in [BUTTON_EDIT, BUTTON_LEFT, BUTTON_RIGHT, BUTTON_UP, BUTTON_DOWN, BUTTON_NEXT_PRESET, BUTTON_RESET]:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

lcd_small = CharLCD('PCF8574', LCD_SMALL_ADDR, cols=16, rows=2)
lcd_big = CharLCD('PCF8574', LCD_BIG_ADDR, cols=20, rows=4)

spi = spidev.SpiDev()
spi.open(0, 0)  # MCP3208 CS0 = GPIO8
spi.max_speed_hz = 1350000

# --- SAMPLES ---
def loadSamplesFromSD(path=SAMPLES_PATH):
    samples = ["Empty"]
    try:
        for fname in os.listdir(path):
            if fname.lower().endswith(".wav"):
                samples.append(fname[:-4])
    except Exception:
        pass
    return samples

samples = loadSamplesFromSD()

# --- PRESET STRUCTURE ---
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
selection = 0
editMode = False

# --- JSON SAVE/LOAD ---
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

# --- LCD RENDERING ---
def show_small():
    lcd_small.cursor_pos = (0, 0)
    lcd_small.write_string(f"PR {currentPreset+1:02d}   CH {currentChannel+1:02d}   ")
    lcd_small.cursor_pos = (1, 0)
    lcd_small.write_string(
        f"{preset[currentPreset][currentChannel]['barCount']:04d}    "
        f"{preset[currentPreset][currentChannel]['velocity']:04d}    "
    )

def show_big():
    ch = preset[currentPreset][currentChannel]
    # 1-2: název samplu (bez .wav)
    name = ch['sound']
    lcd_big.cursor_pos = (0, 0)
    lcd_big.write_string(name[:20].ljust(20))
    lcd_big.cursor_pos = (1, 0)
    lcd_big.write_string(name[20:40].ljust(20) if len(name) > 20 else " " * 20)
    # 3: 4x5 znaků
    row3 = ""
    row3 += ("On" if ch['active'] else "Off").ljust(5)
    row3 += ("Fix" if ch['playFix'] else "Rand").ljust(5)
    if ch['playFix']:
        row3 += f"{playOptions[ch['playEvery']]:>5}".ljust(5)
        row3 += f"{playOptions[ch['playPosition']]:>5}".ljust(5)
    else:
        row3 += f"{playOptions[ch['randomFrom']]:>5}".ljust(5)
        row3 += f"{playOptions[ch['randomTo']]:>5}".ljust(5)
    lcd_big.cursor_pos = (2, 0)
    lcd_big.write_string(row3[:20])
    # 4: volume, hitThreshold, releaseThreshold, debounce
    row4 = f"{ch['channelVolume']:>5}{ch['hitThreshold']:>5}{ch['releaseThreshold']:>5}{ch['debounce']:>5}"
    lcd_big.cursor_pos = (3, 0)
    lcd_big.write_string(row4[:20])

# --- MCP3208 ---
def read_channel(channel):
    adc = spi.xfer2([6 | (channel >> 2), (channel & 3) << 6, 0])
    data = ((adc[1] & 15) << 8) | adc[2]
    return data

# --- MAIN LOOP ---
show_small()
show_big()

try:
    while True:
        # Čtení správného kanálu z MCP3208
        ch = preset[currentPreset][currentChannel]
        val = read_channel(currentChannel)
        velocity = int((val / 4095) * 100)
        now = time.time()

        # Detekce úderu s debounce a threshold
        if ch['armed'] and val > ch['hitThreshold']:
            if (now - ch['last_hit_time']) * 1000 > ch['debounce']:
                ch['hitCount'] += 1
                ch['barCount'] += 1
                ch['velocity'] = velocity
                ch['last_hit_time'] = now
                ch['armed'] = False
                show_small()
        if not ch['armed'] and val < ch['releaseThreshold']:
            ch['armed'] = True

        # --- Tlačítka ---
        if GPIO.input(BUTTON_UP) == GPIO.LOW:
            currentChannel = (currentChannel + 1) % NUM_CHANNELS
            show_small(); show_big(); time.sleep(0.2)
        if GPIO.input(BUTTON_DOWN) == GPIO.LOW:
            currentChannel = (currentChannel - 1) % NUM_CHANNELS
            show_small(); show_big(); time.sleep(0.2)
        if GPIO.input(BUTTON_NEXT_PRESET) == GPIO.LOW:
            currentPreset = (currentPreset + 1) % NUM_PRESETS
            show_small(); show_big(); time.sleep(0.2)
        if GPIO.input(BUTTON_RESET) == GPIO.LOW:
            for p in range(NUM_PRESETS):
                for c in range(NUM_CHANNELS):
                    preset[p][c]['hitCount'] = 0
                    preset[p][c]['barCount'] = 0
            show_small(); time.sleep(0.2)
        # Editace a výběr políčka (základ)
        if GPIO.input(BUTTON_LEFT) == GPIO.LOW:
            selection = (selection - 1) % 9
            show_big(); time.sleep(0.2)
        if GPIO.input(BUTTON_RIGHT) == GPIO.LOW:
            selection = (selection + 1) % 9
            show_big(); time.sleep(0.2)
        if GPIO.input(BUTTON_EDIT) == GPIO.LOW:
            editMode = not editMode
            if not editMode:
                saveShitToJSON()
            # Blikání/označení políčka by se řešilo zde
            show_big(); time.sleep(0.2)
        time.sleep(0.01)

except KeyboardInterrupt:
    spi.close()
    lcd_small.clear()
    lcd_big.clear()
    GPIO.cleanup()
    print("Bye")
