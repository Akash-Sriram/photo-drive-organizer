import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import threading
import sys
import os

# Import the orchestrator
from organize_photos_unified import main as run_organizer

class RedirectText:
    """Class to redirect stdout to a Tkinter ScrolledText widget."""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)

    def flush(self):
        pass

class OrganizerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Photo & Drive Organizer")
        self.root.geometry("600x500")

        # variables
        self.src_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.execute_var = tk.BooleanVar(value=False)
        self.utc_var = tk.StringVar(value="5:30")

        self.setup_ui()

    def setup_ui(self):
        padding = 10

        # --- Source Directory ---
        frame_src = tk.Frame(self.root)
        frame_src.pack(fill=tk.X, padx=padding, pady=5)
        
        tk.Label(frame_src, text="Source Directories (Comma separated):").pack(anchor=tk.W)
        self.entry_src = tk.Entry(frame_src, textvariable=self.src_var)
        self.entry_src.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        tk.Button(frame_src, text="Browse...", command=self.browse_src).pack(side=tk.RIGHT)

        # --- Destination Directory ---
        frame_dest = tk.Frame(self.root)
        frame_dest.pack(fill=tk.X, padx=padding, pady=5)
        
        tk.Label(frame_dest, text="Destination Directory:").pack(anchor=tk.W)
        self.entry_dest = tk.Entry(frame_dest, textvariable=self.dest_var)
        self.entry_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        tk.Button(frame_dest, text="Browse...", command=self.browse_dest).pack(side=tk.RIGHT)

        # --- Options ---
        frame_opts = tk.Frame(self.root)
        frame_opts.pack(fill=tk.X, padx=padding, pady=5)

        tk.Checkbutton(frame_opts, text="Execute (Uncheck for Dry Run)", variable=self.execute_var).pack(side=tk.LEFT)
        
        tk.Label(frame_opts, text="UTC Offset:").pack(side=tk.LEFT, padx=(20, 5))
        tk.Entry(frame_opts, textvariable=self.utc_var, width=8).pack(side=tk.LEFT)

        # --- Start Button ---
        self.btn_start = tk.Button(self.root, text="Start Organizing", command=self.start_process, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        self.btn_start.pack(pady=10)

        # --- Log View ---
        tk.Label(self.root, text="Logs:").pack(anchor=tk.W, padx=padding)
        self.log_area = scrolledtext.ScrolledText(self.root, state=tk.DISABLED, height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=padding, pady=(0, padding))

        # Redirect stdout
        sys.stdout = RedirectText(self.log_area)
        sys.stderr = RedirectText(self.log_area)

    def browse_src(self):
        folder = filedialog.askdirectory()
        if folder:
            current = self.src_var.get()
            if current:
                self.src_var.set(f"{current},{folder}")
            else:
                self.src_var.set(folder)

    def browse_dest(self):
        folder = filedialog.askdirectory()
        if folder:
            self.dest_var.set(folder)

    def start_process(self):
        src = self.src_var.get().strip()
        dest = self.dest_var.get().strip()
        
        if not src or not dest:
            messagebox.showerror("Error", "Please specify both Source and Destination directories.")
            return

        # Disable button during run
        self.btn_start.config(state=tk.DISABLED)
        self.log_area.config(state=tk.NORMAL)
        self.log_area.delete('1.0', tk.END)
        self.log_area.config(state=tk.DISABLED)

        # Prepare arguments
        args_list = ["--src", src, "--dest", dest]
        if self.execute_var.get():
            args_list.append("--execute")
        if self.utc_var.get():
            args_list.extend(["--utc-offset", self.utc_var.get()])

        # Run in separate thread
        t = threading.Thread(target=self.run_process_task, args=(args_list,))
        t.daemon = True
        t.start()

    def run_process_task(self, args_list):
        try:
            print("--- Launching Photo Organizer via GUI ---")
            run_organizer(args_list)
            print("\n--- Finished ---")
        except Exception as e:
            print(f"\nError occurred: {e}")
        finally:
            self.root.after(0, lambda: self.btn_start.config(state=tk.NORMAL))

if __name__ == "__main__":
    root = tk.Tk()
    app = OrganizerGUI(root)
    root.mainloop()
