# ITk Strip Module OCR Checker

This script was developed in conjunction with SCIPP (Santa Cruz Institute for Particle Physics) as part of quality control for ATLAS ITk strip module assembly. It uses OCR to automatically read hybrid serial numbers from photos of modules and cross-checks them against the ITk database to catch any assembly errors.

## How it works

For each image the script:
1. Finds and reads the module name from the label sticker on the transport frame
2. Locates and reads the hybrid serial number printed on the PCB
3. Looks up the expected hybrid for that module in the ITk database
4. Reports any mismatches or images it couldn't read

The module name read from the label is what decides which module an image belongs to. If it disagrees with the file name, the image is marked as failed.

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
imageFolders = [
    'path/to/your/images',
]
```

Then run:
```
python module_ocr.py
```

There is also a notebook version (`module_ocr.ipynb`) that does the same thing, if you'd rather run it cell by cell.

## Output

Every image ends up in one of three groups:

- **Passed**: serial on board matches the database
- **Warning**: serial is almost the same as the database (one character off, usually an OCR slip). Worth a quick look by hand
- **Failed**: anything that couldn't be confirmed. This includes serials that don't match (potential assembly error worth investigating), images where the serial or module name couldn't be read (usually a blurry image or text out of frame), and a label that doesn't match the file name

If the serial on a board belongs to a different module, the failed entry says so, and these are listed first.

## Troubleshooting

**API connection error / access code error**
If the script fails with a 500 HTTP error or "Identity not Authenticated", your access codes are either missing, incorrect, or expired. Make sure your `.env` file exists in the same directory as the script and contains the correct credentials. Contact your lab administrator if you need new credentials.

**"found 0 images"**
Check that the paths in `imageFolders` are correct and that the images are `.jpg` or `.JPG` files. Use the full absolute path e.g. `/Users/yourname/Downloads/images`.

**Lots of failed with "error: ... Connection" or "Failed to resolve"**
Your internet dropped during the run, so the database was never checked for those images. Rerun once you're back online.

**First run is slow**
The first time you execute the script, it must download the EasyOCR language model (~100MB). This is normal and only happens once. Subsequent runs will be much faster.

## Notes

- Tested on Python 3.13, compatible with Python 3.8 and later.
- Tested on SCIPP lab images with ~90% accuracy across 124 images.
- Access codes are not included in this repository — store them in a local `.env` file as described above.
