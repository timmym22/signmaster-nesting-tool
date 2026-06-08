# main.py
# Entry point for the SignMaster Nesting Tool.
# This file does nothing except start the application.
# All logic lives in the core/ and ui/ modules.

import multiprocessing
import tkinter as tk
from ui.app import NestingApp


def main():
    root = tk.Tk()
    app  = NestingApp(root)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()