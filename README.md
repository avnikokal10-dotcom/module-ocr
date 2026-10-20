# ITk Strip Module OCR Checker

This script was developed in conjunction with SCIPP (Santa Cruz Institute for Particle Physics) as part of quality control for ATLAS ITk strip module assembly. It uses OCR to automatically read hybrid serial numbers from photos of modules and cross-checks them against the ITk database to catch any assembly errors.

## How it works

For each image the script:
1. Finds and reads the module name from the label sticker
2. Locates and reads the hybrid serial number printed on the PCB
3. Looks up the expected hybrid for that module in the ITk database
4. Reports mismatches, near-matches, and images it couldn't read

The module is identified from the label only. The image file name is never used.

## Getting started

Install the required packages:
```
pip install -r requirements.txt
```

**Set up your access codes:**

Create a file called `.env` in the same directory as the script with the following contents:
```
ITKDB_ACCESS_CODE1=your_access_code_1
ITKDB_ACCESS_CODE2=your_access_code_2
```
Contact your lab administrator for credentials. Do not share this file or commit it to GitHub.

**Set the folder(s) containing your images:**
```python
image_folders = [
    'path/to/your/images',
]
```

Then run:
```
python module_ocr.py
```

There is also a notebook version (`module_ocr_notebook.ipynb`) that does the same thing but also displays the label and serial pictures for every warning, failed and unread image. Use it when you want to look at the flagged images without opening each photo. Use the script for a quick text report.

## Output

Every image ends up in one of four groups:

- **Passed**: serial on board matches the database
- **Warning**: serial is one character off from the database, usually an OCR mistake. The hybrid number (the H digit) still has to match exactly. Worth a quick look by eye.
- **Failed**: a serial was read but doesn't match the database (potential assembly error worth investigating, or a bad read)
- **Unread**: the serial or module name couldn't be read, the module wasn't found in the database, or there was an error (usually a blurry image, text out of frame, or a dropped connection). The reason is printed for each one.

## Troubleshooting

**API connection error / access code error**
If the script fails with a 500 HTTP error or "Identity not Authenticated", your access codes are either missing, incorrect, or expired. Make sure your `.env` file exists in the same directory as the script and contains the correct credentials. Contact your lab administrator if you need new credentials.

**"found 0 images"**
Check that the paths in `image_folders` are correct and that the images are `.jpg` or `.JPG` files. Use the full absolute path e.g. `/Users/yourname/Downloads/images`.

**Unread with "error: ... Connection" or "Failed to resolve"**
Your internet or the database connection dropped, so those images were never checked. Rerun once you're back online.

**First run is slow**
The first time you execute the script, it must download the EasyOCR language model (~100MB). This is normal and only happens once. Subsequent runs will be much faster.

## Notes

- Tested on Python 3.13.9. The pinned package versions need Python 3.11 or newer.
- On 491 SCIPP lab images, about 86% passed and about 8% more were warnings.
- If a new batch uses a serial prefix other than `GPC`, `DBS` or `DSG`, add it to `VALID_PREFIXES`.
