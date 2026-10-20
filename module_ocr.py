#!/usr/bin/env python
# coding: utf-8

# In[9]:


from PIL import Image, ImageOps
from pathlib import Path
import easyocr
import re
import numpy as np
import logging
import warnings

warnings.filterwarnings('ignore')
logging.getLogger('easyocr').setLevel(logging.ERROR)

from dotenv import load_dotenv
load_dotenv()

# set the folders containing your images here
image_folders = [
    'path/to/your/images',
]

SERIAL_BOX = (0.57, 0.32, 0.68, 0.48)
SERIAL_BOX_WIDE = (0.54, 0.29, 0.71, 0.51)

VALID_PREFIXES = {'GPC', 'DBS', 'DSG'}

FOLD_MAP = str.maketrans({'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'S': '5',
                          'B': '8', 'Z': '2', 'G': '6', 'A': '4'})
DIGIT_MAP = str.maketrans({'O': '0', 'I': '1', 'L': '1', 'S': '5', 'B': '8', 'Z': '2', 'G': '6', '(': '1', '|': '1'})
RANKS = {'ok': 0, 'warning': 1, 'wrong': 2}

BLOCK2_CONFUSIONS = {'O': '0', 'C': '0', 'U': '0', 'Q': '0',
                     'I': '1', 'L': '1', 'N': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}
LETTER_CONFUSIONS = {'I': '1', 'O': '0', 'S': '5', 'B': '8', 'G': '6', 'Z': '2', 'A': '4'}
DIGIT_TO_LETTER = {'8': 'B', '0': 'O', '1': 'I', '5': 'S', '9': 'A'}
LETTER_TO_DIGIT = {'B': '8', 'O': '0', 'I': '1', 'S': '5', 'A': '4', 'Z': '2', 'G': '6'}

NOISE_LETTERS = {'H', 'R', 'U', 'Q', 'L', 'J', 'T', 'N',
                 'X', 'Y', 'Z', 'K', 'M', 'W', 'V', 'S', 'O'}
DIGIT_ONLY = {'I', 'O', 'S', 'G'}

import itkdb
client = itkdb.Client()


def get_property_by_name(comp, prop_name):
    if not comp.get("properties"):
        return None
    properties = [p for p in comp["properties"] if p["name"] == prop_name]
    if len(properties) == 0:
        return None
    return properties[0]["value"]


def get_module(module_name):
    if not module_name or not ('SCIPP-PRO_LS-' in module_name or 'SCIPP-PS_LS-' in module_name):
        return None
    cs = list(client.get("listComponents", json={"filterMap": {"project": "S", "state": ["ready"], "propertyFilter": [{"code": "LOCALNAME", "operator": "=", "value": module_name}]}}, headers={"Cache-Control": "no-cache"}))
    if not len(cs) == 1:
        return None
    return client.get("getComponent", json={"component": cs[0]['serialNumber']}, headers={"Cache-Control": "no-cache"})


def get_hybrid_child(c):
    hybrid_children = []
    if not c:
        return None
    for child in c['children']:
        if not child['component']:
            continue
        if not child['componentType']['code'] == 'HYBRID_ASSEMBLY':
            continue
        hybrid = client.get("getComponent", json={"component": child['component']['serialNumber']}, headers={"Cache-Control": "no-cache"})
        hybrid_children.append(get_property_by_name(hybrid, 'Local Name'))
    return hybrid_children


def other_type(name):
    if 'SCIPP-PRO_LS-' in name:
        return name.replace('SCIPP-PRO_LS-', 'SCIPP-PS_LS-')
    return name.replace('SCIPP-PS_LS-', 'SCIPP-PRO_LS-')


def get_module_hybrid(module_name):
    names = [module_name, other_type(module_name)]
    if module_name[-4] == '8':
        names += [n[:-4] + '0' + n[-3:] for n in names]
    for name in names:
        comp = get_module(name)
        if comp:
            return name, get_hybrid_child(comp)
    return module_name, None


def ocr_to_db_format(prefix, gpc_block, four_digit, letter, h_digit):
    block2 = four_digit.lstrip('0') or '0'
    block2 = block2.zfill(3)
    return f"{prefix}{gpc_block}_X_{block2}_{letter}_H{h_digit}"


def fold(s):
    return re.sub(r'[^A-Z0-9]', '', s.upper()).translate(FOLD_MAP)


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def compare(candidate, db_hybrids):
    if candidate in db_hybrids:
        return 'ok'
    for h in db_hybrids:
        if h and candidate[-1] == h[-1] and edit_distance(fold(candidate), fold(h)) <= 1:
            return 'warning'
    return 'wrong'


def open_image(filepath):
    with Image.open(filepath) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.width > img.height:
            img = img.rotate(90, expand=True)
        return img


def remove_black_border(img, threshold=30):
    gray = np.array(img.convert('L'))
    rows = np.where(gray.mean(axis=1) > threshold)[0]
    cols = np.where(gray.mean(axis=0) > threshold)[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    return img.crop((cols[0], rows[0], cols[-1], rows[-1]))


def fix_module_name(result, min_confidence=0.1):
    kept_text = ' '.join([text for (_, text, conf) in result if conf >= min_confidence])
    match = re.search(r'(PRO|PS)[-_ ]*[LI]S[-_ ]*([0-9OILSBZG(|]{3,4})', kept_text, re.IGNORECASE)
    if match:
        digits = match.group(2).upper().translate(DIGIT_MAP).zfill(4)[-4:]
        prefix = 'SCIPP-PS' if match.group(1).upper() == 'PS' else 'SCIPP-PRO'
        return f"{prefix}_LS-{digits}"
    match2 = re.search(r'[LI]S[-_ ]*([0-9OILSBZG(|]{3,4})', kept_text, re.IGNORECASE)
    if match2:
        digits = match2.group(1).upper().translate(DIGIT_MAP).zfill(4)[-4:]
        return f"SCIPP-PRO_LS-{digits}"
    return None


def crop_label(img):
    w, h = img.size
    crop = img.crop((int(w*0.15), 0, int(w*0.80), int(h*0.08)))
    return ImageOps.autocontrast(crop, cutoff=1)


def crop_label_bottom(img):
    w, h = img.size
    crop = img.crop((int(w*0.15), int(h*0.92), int(w*0.80), h))
    return ImageOps.autocontrast(crop.rotate(180), cutoff=1)


def find_gpc_crop(img, box=SERIAL_BOX):
    w, h = img.size
    serial = img.crop((int(w*box[0]), int(h*box[1]), int(w*box[2]), int(h*box[3])))
    serial = serial.rotate(90, expand=True)
    return np.array(serial)


def is_valid_block2(val, gpc_block):
    return (len(val) == 4 and val.isdigit() and
            val.startswith('0') and val != gpc_block and val != '0000')


def get_serial_from_result(result, sw):
    def x_center(box):
        return (min(pt[0] for pt in box) + max(pt[0] for pt in box)) / 2 / sw

    prefix = None
    gpc_block = None
    four_digit = None
    letter = None
    h_digit = None
    gpc_xc = 0.0
    block2_xc = 0.0
    letter_xc = 0.0

    detections = sorted(result, key=lambda r: x_center(r[0]))

    for (box, text, conf) in detections:
        xc = x_center(box)
        text_up = text.upper().replace(' ', '')
        for p in VALID_PREFIXES:
            if p in text_up and prefix is None:
                m = re.search(r'\d{4}', text_up)
                if m:
                    prefix = p
                    gpc_block = m.group(0)
                    gpc_xc = xc
                    rest = re.sub(r'[^A-Z0-9]', '', text_up[m.end():])
                    if len(rest) >= 4:
                        cleaned = ''.join([BLOCK2_CONFUSIONS.get(c, c) for c in rest[:4]])
                        if is_valid_block2(cleaned, gpc_block):
                            four_digit = cleaned
                            block2_xc = max(pt[0] for pt in box) / sw

    for (box, text, conf) in detections:
        xc = x_center(box)
        text_up = text.upper().replace(' ', '')
        clean_alnum = re.sub(r'[^A-Z0-9]', '', text_up)

        if gpc_block and four_digit is None and xc > gpc_xc + 0.05 and xc < 0.65:
            candidate = None
            for token in text_up.split():
                if len(token) >= 4:
                    sub = token[:4]
                    cleaned = ''.join([BLOCK2_CONFUSIONS.get(c, c) for c in sub])
                    if is_valid_block2(cleaned, gpc_block):
                        candidate = cleaned
                        break
            if not candidate:
                m = re.search(r'(0\d{3})', text_up)
                if m and is_valid_block2(m.group(1), gpc_block):
                    candidate = m.group(1)
            if candidate:
                four_digit = candidate
                block2_xc = xc

        elif four_digit and letter is None and xc > block2_xc + 0.02 and xc < block2_xc + 0.22:
            clean = re.sub(r'[^A-Za-z0-9]', '', text.strip())
            m = re.search(r'([A-Za-z])(\d?)', clean)
            if m:
                l = m.group(1).upper()
                d = m.group(2)
                if l not in NOISE_LETTERS and l not in DIGIT_ONLY:
                    letter = l
                    letter_xc = xc
                    if d and not h_digit:
                        mapped_d = LETTER_CONFUSIONS.get(d.upper(), d)
                        if mapped_d.isdigit():
                            h_digit = mapped_d
            if letter is None and len(clean) == 2:
                l = clean[0].upper()
                second = clean[1].upper()
                if l.isdigit():
                    l = DIGIT_TO_LETTER.get(l, l)
                if l.isalpha() and l not in NOISE_LETTERS and l not in DIGIT_ONLY:
                    mapped_second = LETTER_CONFUSIONS.get(second, second)
                    if not mapped_second.isdigit():
                        mapped_second = LETTER_TO_DIGIT.get(second, second)
                    if mapped_second.isdigit():
                        letter = l
                        letter_xc = xc
                        h_digit = mapped_second
            if letter is None and '8' in clean_alnum and len(clean_alnum) <= 2:
                letter = 'B'
                letter_xc = xc
            elif letter is None and '9' in clean_alnum and len(clean_alnum) <= 2:
                letter = 'A'
                letter_xc = xc
            elif letter is None and '4' in clean_alnum and len(clean_alnum) <= 2:
                letter = 'A'
                letter_xc = xc

        elif four_digit and h_digit is None and xc > max(block2_xc + 0.15, letter_xc + 0.10):
            m = re.search(r'H([A-Z0-9])', text_up)
            if m:
                raw_d = m.group(1)
                mapped_d = LETTER_CONFUSIONS.get(raw_d, raw_d)
                if mapped_d.isdigit():
                    h_digit = mapped_d
            if not h_digit and conf > 0.05 and xc > letter_xc + 0.15:
                if len(clean_alnum) == 1 and clean_alnum.isdigit():
                    h_digit = clean_alnum
                elif len(clean_alnum) == 2 and clean_alnum[0] in ('1', 'I', 'L', 'T') and clean_alnum[1].isdigit():
                    h_digit = clean_alnum[1]

    return prefix, gpc_block, four_digit, letter, h_digit


def read_serial(reader, img, db_hybrids):
    best = (3, 'unread', None)
    for box in (SERIAL_BOX, SERIAL_BOX_WIDE):
        crop = find_gpc_crop(img, box)
        for scale in (1, 2):
            arr = crop
            if scale > 1:
                arr = np.array(Image.fromarray(crop).resize((crop.shape[1] * scale, crop.shape[0] * scale)))
            result = reader.readtext(arr)
            parts = get_serial_from_result(result, arr.shape[1])
            if not all(parts):
                continue
            candidate = ocr_to_db_format(*parts)
            status = compare(candidate, db_hybrids)
            if RANKS[status] < best[0]:
                best = (RANKS[status], status, candidate)
            if status == 'ok':
                return status, candidate
    return best[1], best[2]


image_files = []
for folder in image_folders:
    path = Path(folder)
    image_files.extend(path.glob('*.JPG'))
    image_files.extend(path.glob('*.jpg'))
image_files = sorted(image_files)
print(f"found {len(image_files)} images\n")

reader = easyocr.Reader(['en'])
results = []

for filepath in image_files:
    filename = filepath.name

    try:
        img = open_image(filepath)
        img = remove_black_border(img)

        label_result = reader.readtext(np.array(crop_label(img)))
        module_name = fix_module_name(label_result)

        if not module_name:
            label_result = reader.readtext(np.array(crop_label_bottom(img)))
            module_name = fix_module_name(label_result)
            if module_name:
                img = img.rotate(180)

        if not module_name:
            results.append({'file': filename, 'status': 'could not read module name'})
            continue

        module_name, db_hybrids = get_module_hybrid(module_name)

        if db_hybrids is None:
            results.append({'file': filename, 'module': module_name, 'status': 'module not found in database'})
            continue

        if not db_hybrids:
            results.append({'file': filename, 'module': module_name, 'status': 'module has no hybrid in database'})
            continue

        status, candidate = read_serial(reader, img, db_hybrids)
        rec = {'file': filename, 'module': module_name, 'db_hybrid': ', '.join(db_hybrids), 'candidate': candidate}

        if status == 'unread':
            rec['status'] = 'could not read serial'
        else:
            rec['status'] = status
        results.append(rec)

    except Exception as e:
        results.append({'file': filename, 'status': f'error: {e}'})

total = len(results)
passed = [r for r in results if r.get('status') == 'ok']
warned = [r for r in results if r.get('status') == 'warning']
failed = [r for r in results if r.get('status') == 'wrong']
unread = [r for r in results if r.get('status') not in ('ok', 'warning', 'wrong')]

print(f"Results:")
print(f"total images processed: {total}")
print(f"passed: {len(passed)} ({round(len(passed)/total*100) if total else 0}%)")
print(f"warnings: {len(warned)}")
print(f"failed: {len(failed)}")
print(f"unread: {len(unread)}\n")

if failed:
    print(f"Failed: hybrid on board does not match database")
    for r in failed:
        print(f"\n  module: {r['module']}")
        print(f"  expected: {r['db_hybrid']}")
        print(f"  read: {r.get('candidate', 'could not read')}\n")

if warned:
    print(f"Warnings: serial is almost the same as the database, check by hand")
    for r in warned:
        print(f"\n  module: {r['module']}")
        print(f"  expected: {r['db_hybrid']}")
        print(f"  read: {r['candidate']}\n")

if unread:
    print(f"Unread: could not extract serial from image")
    for r in unread:
        print(f"\n  file: {r['file']}")
        if r.get('module'):
            print(f"  module: {r['module']}")
        if r.get('db_hybrid'):
            print(f"  expected: {r['db_hybrid']}")
        print(f"  reason: {r['status']}")
