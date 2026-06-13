"""
setup.py for creating macOS .app bundle
Usage: python3 setup.py py2app
"""

from setuptools import setup

APP = ['job_applier_gui.py']
DATA_FILES = [
    ('', ['naukri_job_applier.py'])
]
OPTIONS = {
    'argv_emulation': False,
    'packages': ['playwright', 'dotenv', 'tkinter'],
    'plist': {
        'CFBundleName': 'Naukri Job Applier',
        'CFBundleDisplayName': 'Naukri Job Applier',
        'CFBundleIdentifier': 'com.naukri.jobapplier',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
    },
    'iconfile': None,  # Set to 'icon.icns' if you have an icon
}

setup(
    name='Naukri Job Applier',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
