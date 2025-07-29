import os

usb_path = "/media/tom/ZVUKY/"

try:
    files = os.listdir(usb_path)
    print("Obsah složky ZVUKY:")
    for fname in files:
        print(fname)
except Exception as e:
    print("Chyba při čtení složky:", e)
