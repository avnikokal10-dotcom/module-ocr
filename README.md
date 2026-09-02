# ITk Strip Module OCR Checker

This script was developed in conjunction with SCIPP (Santa Cruz Institute for Particle Physics) as part of quality control for ATLAS ITk strip module assembly. It uses OCR to automatically read hybrid serial numbers from photos of modules and cross-checks them against the ITk database to catch any assembly errors.

## How it works

For each image the script:

1. Finds and reads the module name from the label sticker on the transport frame
2. Locates and reads the hybrid serial number printed on the PCB
3. Looks up the expected hybrid for that module in the ITk database
4. Reports any mismatches or images it couldn't read

## Getting started

Install the required packages:

```
pip install easyocr pillow numpy itkdb
```

Then open the script and fill in two things at the top:

**Your database access codes:**

```python
os.environ["ITKDB_ACCESS_CODE1"] = "your_access_code_1"
os.environ["ITKDB_ACCESS_CODE2"] = "your_access_code_2"
```

**The folder(s) containing your images:**

```python
imageFolders = [
    'path/to/your/images',
]
```

Then it is ready to run.

```
python module_ocr.py
```

## Output

- **Passed**: serial on board matches the database
- **Failed**: serial was read but doesn't match (potential assembly error worth investigating)
- **Unread**: couldn't extract the serial from the image (usually means the image is blurry or the text is out of frame)

## Troubleshooting

**API connection error / access code error**
If the script fails with a 500 HTTP error or "Secret must be not null", your access codes are either missing or incorrect. Make sure you've uncommented and filled in the `os.environ` lines at the top of the script before running, and that the codes haven't expired. Contact your lab administrator if you need new credentials.

**"found 0 images"**
Check that the paths in `imageFolders` are correct and that the images are `.jpg` or `.JPG` files.

**Low accuracy / many unread images**
The script works best with high resolution photos taken straight-on. Images that are blurry, heavily shadowed, or where the module is positioned off-center may not read correctly.

**First run is slow**
The first time you execute the script, it must download the EasyOCR language model (~100MB). This is normal and only happens once. Subsequent runs will be much faster.

## Notes

- Tested on Python 3.13, compatible with Python 3.8 and later.
- Tested on SCIPP lab images with ~90% accuracy across 124 images.
- Access codes are not included in this repository.
