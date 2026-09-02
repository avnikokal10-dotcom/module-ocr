#!/usr/bin/env python
# coding: utf-8

# In[1]:


from PIL import Image, ImageOps
import easyocr
import re
import numpy as np
import glob
import os
import logging
import warnings

warnings.filterwarnings('ignore')
logging.getLogger('easyocr').setLevel(logging.ERROR)

from dotenv import load_dotenv
load_dotenv() 

# set the folders containing your images here
imageFolders = [
    'path/to/your/images',
]

import itkdb
client = itkdb.Client()


def getPropertyByName(comp, prop_name):
    if not comp.get("properties"):
        return None
    properties = [p for p in comp["properties"] if p["name"] == prop_name]
    if len(properties) == 0:
        return None
    return properties[0]["value"]


def getModule(module_name):
    if not ('SCIPP-PRO_LS-' in module_name or 'SCIPP-PS_LS-' in module_name):
        return None
    cs = list(client.get("listComponents", json={"filterMap": {"project": "S", "state": ["ready"], "propertyFilter": [{"code": "LOCALNAME", "operator": "=", "value": module_name}]}}, headers={"Cache-Control": "no-cache"}))
    if not len(cs) == 1:
        return None
    return client.get("getComponent", json={"component": cs[0]['serialNumber']}, headers={"Cache-Control": "no-cache"})


def getHybridChild(c):
    hybrid_children = []
    if not c:
        return None
    for child in c['children']:
        if not child['component']:
            continue
        if not child['componentType']['code'] == 'HYBRID_ASSEMBLY':
            continue
        hybrid = client.get("getComponent", json={"component": child['component']['serialNumber']}, headers={"Cache-Control": "no-cache"})
        hybrid_children.append(getPropertyByName(hybrid, 'Local Name'))
    return hybrid_children


def getModuleHybrid(module_name):
    return getHybridChild(getModule(module_name))


def ocrToDbFormat(prefix, gpc_block, four_digit, letter, h_digit):
    block2 = four_digit.lstrip('0') or '0'
    block2 = block2.zfill(3)
    return f"{prefix}{gpc_block}_X_{block2}_{letter}_H{h_digit}"


def openImage(filepath):
    with Image.open(filepath) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.width > img.height:
            img = img.rotate(90, expand=True)
        return img


def removeBlackBorder(img, threshold=30):
    gray = np.array(img.convert('L'))
    rows = np.where(gray.mean(axis=1) > threshold)[0]
    cols = np.where(gray.mean(axis=0) > threshold)[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    return img.crop((cols[0], rows[0], cols[-1], rows[-1]))


def fixModuleName(result, min_confidence=0.2):
    kept_text = ' '.join([text for (_, text, conf) in result if conf >= min_confidence])
    match = re.search(r'(SCIPP-(?:PRO|PS)_LS-(\d+))', kept_text, re.IGNORECASE)
    if match:
        digits = match.group(2).zfill(4)[-4:]
        prefix = 'SCIPP-PS' if 'PS' in match.group(1).upper() else 'SCIPP-PRO'
        return f"{prefix}_LS-{digits}"
    match2 = re.search(r'LS[-_]?(\d+)', kept_text, re.IGNORECASE)
    if match2:
        digits = match2.group(1).zfill(4)[-4:]
        return f"SCIPP-PRO_LS-{digits}"
    return None


def cropLabel(img):
    w, h = img.size
    crop = img.crop((int(w*0.15), 0, int(w*0.80), int(h*0.08)))
    return ImageOps.autocontrast(crop, cutoff=1)


def cropLabelBottom(img):
    w, h = img.size
    crop = img.crop((int(w*0.15), int(h*0.92), int(w*0.80), h))
    return ImageOps.autocontrast(crop.rotate(180), cutoff=1)


def findGpcCrop(img):
    w, h = img.size
    serial = img.crop((int(w*0.57), int(h*0.32), int(w*0.68), int(h*0.48)))
    serial = serial.rotate(90, expand=True)
    return np.array(serial)


def getSerialFromResult(result, sw, debug=False):
    valid_prefixes = {'GPC', 'DBS', 'DSG'}
    block2_confusions = {'O': '0', 'C': '0', 'U': '0', 'Q': '0',
                         'I': '1', 'L': '1', 'N': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}
    letter_confusions = {'I': '1', 'O': '0', 'S': '5', 'B': '8', 'G': '6', 'Z': '2', 'A': '4'}
    digit_to_letter = {'8': 'B', '0': 'O', '1': 'I', '5': 'S', '9': 'A'}
    letter_to_digit = {'B': '8', 'O': '0', 'I': '1', 'S': '5', 'A': '4', 'Z': '2', 'G': '6'}

    def isValidBlock2(val, gpc_block):
        return (len(val) == 4 and val.isdigit() and
                val.startswith('0') and val != gpc_block and val != '0000')

    noise_letters = {'H', 'R', 'U', 'Q', 'L', 'J', 'T', 'N',
                     'X', 'Y', 'Z', 'K', 'M', 'W', 'V', 'S', 'O'}
    digit_only = {'I', 'O', 'S', 'G'}

    def xCenter(box):
        return (min(pt[0] for pt in box) + max(pt[0] for pt in box)) / 2 / sw

    prefix = None
    gpc_block = None
    four_digit = None
    letter = None
    h_digit = None
    gpc_xc = 0.0
    block2_xc = 0.0
    letter_xc = 0.0

    detections = sorted(result, key=lambda r: xCenter(r[0]))

    if debug:
        print(f"  {'text':20} {'xc':>6} {'conf':>6}  notes")

    for (box, text, conf) in detections:
        xc = xCenter(box)
        text_up = text.upper().replace(' ', '')
        for p in valid_prefixes:
            if p in text_up and prefix is None:
                m = re.search(r'\d{4}', text_up)
                if m:
                    prefix = p
                    gpc_block = m.group(0)
                    gpc_xc = xc
                    if debug:
                        print(f"  {text!r:20} {xc:6.3f} {conf:6.3f}  prefix={prefix} block1={gpc_block}")

    for (box, text, conf) in detections:
        xc = xCenter(box)
        text_up = text.upper().replace(' ', '')
        clean_alnum = re.sub(r'[^A-Z0-9]', '', text_up)
        notes = []

        if gpc_block and four_digit is None and xc > gpc_xc + 0.05 and xc < 0.65:
            candidate = None
            for token in text_up.split():
                if len(token) >= 4:
                    sub = token[:4]
                    cleaned = ''.join([block2_confusions.get(c, c) for c in sub])
                    if isValidBlock2(cleaned, gpc_block):
                        candidate = cleaned
                        break
            if not candidate:
                m = re.search(r'(0\d{3})', text_up)
                if m and isValidBlock2(m.group(1), gpc_block):
                    candidate = m.group(1)
            if candidate:
                four_digit = candidate
                block2_xc = xc
                notes.append(f"block2={four_digit}")

        elif four_digit and letter is None and xc > block2_xc + 0.02 and xc < block2_xc + 0.22:
            clean = re.sub(r'[^A-Za-z0-9]', '', text.strip())
            m = re.search(r'([A-Za-z])(\d?)', clean)
            if m:
                l = m.group(1).upper()
                d = m.group(2)
                if l not in noise_letters and l not in digit_only:
                    letter = l
                    letter_xc = xc
                    notes.append(f"letter={letter}")
                    if d and not h_digit:
                        mapped_d = letter_confusions.get(d.upper(), d)
                        if mapped_d.isdigit():
                            h_digit = mapped_d
                            notes.append(f"h_digit={h_digit}(from letter token)")
            if letter is None and len(clean) == 2:
                l = clean[0].upper()
                second = clean[1].upper()
                if l.isdigit():
                    l = digit_to_letter.get(l, l)
                if l.isalpha() and l not in noise_letters and l not in digit_only:
                    mapped_second = letter_confusions.get(second, second)
                    if not mapped_second.isdigit():
                        mapped_second = letter_to_digit.get(second, second)
                    if mapped_second.isdigit():
                        letter = l
                        letter_xc = xc
                        h_digit = mapped_second
                        notes.append(f"letter={letter} h_digit={h_digit}(2-char token)")
            if letter is None and '8' in clean_alnum and len(clean_alnum) <= 2:
                letter = 'B'
                letter_xc = xc
                notes.append(f"letter=B(from 8)")
            elif letter is None and '9' in clean_alnum and len(clean_alnum) <= 2:
                letter = 'A'
                letter_xc = xc
                notes.append(f"letter=A(from 9)")
            elif letter is None and '4' in clean_alnum and len(clean_alnum) <= 2:
                letter = 'A'
                letter_xc = xc
                notes.append(f"letter=A(from 4)")

        elif four_digit and h_digit is None and xc > max(block2_xc + 0.15, letter_xc + 0.10):
            m = re.search(r'H([A-Z0-9])', text_up)
            if m:
                raw_d = m.group(1)
                mapped_d = letter_confusions.get(raw_d, raw_d)
                if mapped_d.isdigit():
                    h_digit = mapped_d
                    notes.append(f"h_digit={h_digit}(H-pattern)")
            if not h_digit and conf > 0.05 and xc > letter_xc + 0.15:
                if len(clean_alnum) == 1 and clean_alnum.isdigit():
                    h_digit = clean_alnum
                    notes.append(f"h_digit={h_digit}(lone digit)")
                elif len(clean_alnum) == 2 and clean_alnum[0] in ('1', 'I', 'L', 'T') and clean_alnum[1].isdigit():
                    h_digit = clean_alnum[1]
                    notes.append(f"h_digit={h_digit}(2-char fallback)")

        if debug and notes:
            print(f"  {text!r:20} {xc:6.3f} {conf:6.3f}  {', '.join(notes)}")

    if debug:
        print(f"  result: prefix={prefix} block1={gpc_block} block2={four_digit} letter={letter} h_digit={h_digit}")

    return prefix, gpc_block, four_digit, letter, h_digit


image_files = []
for folder in imageFolders:
    image_files += glob.glob(os.path.join(folder, '*.JPG'))
    image_files += glob.glob(os.path.join(folder, '*.jpg'))
image_files = sorted(image_files)
print(f"found {len(image_files)} images\n")

reader = easyocr.Reader(['en'])
results = []
correct = 0
wrong = 0
not_found = 0

for filepath in image_files:
    filename = os.path.basename(filepath)

    try:
        img = openImage(filepath)
        img = removeBlackBorder(img)

        label_result = reader.readtext(np.array(cropLabel(img)))
        module_name = fixModuleName(label_result)

        if not module_name:
            label_result = reader.readtext(np.array(cropLabelBottom(img)))
            module_name = fixModuleName(label_result)
            if module_name:
                img = img.rotate(180)

        serial_crop = findGpcCrop(img)
        serial_result = reader.readtext(serial_crop)

        sw = serial_crop.shape[1]
        prefix, gpc_block, four_digit, letter, h_digit = getSerialFromResult(serial_result, sw)

        if prefix and gpc_block and four_digit and letter and h_digit:
            candidate = ocrToDbFormat(prefix, gpc_block, four_digit, letter, h_digit)
        else:
            candidate = None

        if not module_name:
            not_found += 1
            results.append({'file': filename, 'status': 'could not read module name'})
            continue

        db_hybrids = getModuleHybrid(module_name)

        if not db_hybrids:
            not_found += 1
            results.append({'file': filename, 'module': module_name, 'status': 'not in database'})
            continue

        db_hybrid = db_hybrids[0]
        matched = candidate == db_hybrid

        if matched:
            correct += 1
            results.append({'file': filename, 'module': module_name, 'db_hybrid': db_hybrid, 'status': 'ok'})
        elif candidate is None:
            not_found += 1
            results.append({'file': filename, 'module': module_name, 'db_hybrid': db_hybrid, 'status': 'could not read serial'})
        else:
            wrong += 1
            results.append({'file': filename, 'module': module_name, 'db_hybrid': db_hybrid, 'candidate': candidate, 'status': 'wrong'})

    except Exception as e:
        not_found += 1
        results.append({'file': filename, 'status': f'error: {e}'})

total = len(results)
passed = [r for r in results if r.get('status') == 'ok']
failed = [r for r in results if r.get('status') == 'wrong']
unread = [r for r in results if r.get('status') not in ('ok', 'wrong')]

print(f"Results:")
print(f"total images processed: {total}")
print(f"passed: {len(passed)} ({round(len(passed)/total*100) if total else 0}%)")
print(f"failed: {len(failed)}")
print(f"unread: {len(unread)}\n")

if failed:
    print(f"Failed: hybrid on board does not match database")
    for r in failed:
        print(f"\n  module: {r['module']}")
        print(f"  expected: {r['db_hybrid']}")
        print(f"  read: {r.get('candidate', 'could not read')}\n")

if unread:
    print(f"Unread: could not extract serial from image")
    for r in unread:
        if r.get('db_hybrid'):
            print(f"\n  module: {r['file']}")
            print(f"  expected: {r['db_hybrid']}")
        else:
            print(f"  {r['file']}  ({r.get('status', '')})")






