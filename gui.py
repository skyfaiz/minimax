#!/usr/bin/env python3
"""
H3 Minimax RunPod GUI
Modern graphical interface for H3 Minimax video generation.
"""

import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from typing import Optional
import webbrowser

try:
    from client import H3MinimaxClient, RunPodConfig
except ImportError:
    print("Error: client.py not found. Make sure it's in the same directory.")
    sys.exit(1)


class H3MinimaxGUI:
    """GUI application for H3 Minimax video generation."""
    
    def __init__(self, root: tk.Tk):
        """Initialize the GUI."""
        self.root = root
        self.root.title("H3 Minimax Video Generator")
        self.root.geometry("900x800")
        self.root.resizable(True, True)
        
        # Configure style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Colors
        self.bg_color = "#1e1e1e"
        self.fg_color = "#ffffff"
        self.accent_color = "#007acc"
        self.button_color = "#0e639c"
        
        self.root.configure(bg=self.bg_color)
        
        # Client
        self.client: Optional[H3MinimaxClient] = None
        self.is_generating = False
        
        # Setup UI
        self.setup_ui()
        self.load_config()
    
    def setup_ui(self):
        """Setup the user interface."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Title
        title_label = tk.Label(
            main_frame,
            text="🎬 H3 Minimax Video Generator",
            font=("Segoe UI", 18, "bold"),
            bg=self.bg_color,
            fg=self.fg_color
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Configuration Section
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        config_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(config_frame, text="API Key:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(config_frame, textvariable=self.api_key_var, width=50, show="*")
        self.api_key_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        
        ttk.Label(config_frame, text="Endpoint ID:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.endpoint_var = tk.StringVar()
        self.endpoint_entry = ttk.Entry(config_frame, textvariable=self.endpoint_var, width=50)
        self.endpoint_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        
        ttk.Button(config_frame, text="Save Config", command=self.save_config).grid(
            row=2, column=1, sticky=tk.E, pady=5
        )
        
        config_frame.columnconfigure(1, weight=1)
        
        # Generation Settings
        settings_frame = ttk.LabelFrame(main_frame, text="Generation Settings", padding="10")
        settings_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Mode
        ttk.Label(settings_frame, text="Mode:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.mode_var = tk.StringVar(value="t2v")
        mode_frame = ttk.Frame(settings_frame)
        mode_frame.grid(row=0, column=1, sticky=tk.W, pady=5)
        ttk.Radiobutton(mode_frame, text="Text-to-Video", variable=self.mode_var, value="t2v").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Image-to-Video", variable=self.mode_var, value="i2v").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Reference-to-Video", variable=self.mode_var, value="r2v").pack(side=tk.LEFT, padx=5)
        
        # Prompt
        ttk.Label(settings_frame, text="Prompt:").grid(row=1, column=0, sticky=(tk.W, tk.N), pady=5)
        self.prompt_text = scrolledtext.ScrolledText(settings_frame, height=4, width=60, wrap=tk.WORD)
        self.prompt_text.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.prompt_text.insert("1.0", "Cinematic rooftop chase at dusk, film grain, no text.")
        
        # Image/Reference inputs
        ttk.Label(settings_frame, text="Image/Refs:").grid(row=2, column=0, sticky=tk.W, pady=5)
        image_frame = ttk.Frame(settings_frame)
        image_frame.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5)
        self.image_path_var = tk.StringVar()
        ttk.Entry(image_frame, textvariable=self.image_path_var, width=45).pack(side=tk.LEFT, padx=5)
        ttk.Button(image_frame, text="Browse", command=self.browse_image).pack(side=tk.LEFT)
        
        # Duration
        ttk.Label(settings_frame, text="Duration (s):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.duration_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(settings_frame, from_=1, to=10, increment=0.5, textvariable=self.duration_var, width=10).grid(
            row=3, column=1, sticky=tk.W, pady=5, padx=5
        )
        
        # Aspect Ratio
        ttk.Label(settings_frame, text="Aspect Ratio:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.aspect_var = tk.StringVar(value="16:9 (Widescreen)")
        aspect_combo = ttk.Combobox(settings_frame, textvariable=self.aspect_var, width=25, state="readonly")
        aspect_combo['values'] = (
            "1:1 (Square)",
            "2:3 (Portrait Photo)",
            "3:2 (Photo)",
            "3:4 (Portrait Standard)",
            "4:3 (Standard)",
            "9:16 (Portrait Widescreen)",
            "16:9 (Widescreen)",
            "21:9 (Ultrawide)"
        )
        aspect_combo.grid(row=4, column=1, sticky=tk.W, pady=5, padx=5)
        
        # Megapixels
        ttk.Label(settings_frame, text="Megapixels:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.megapixels_var = tk.DoubleVar(value=0.4)
        ttk.Spinbox(settings_frame, from_=0.2, to=1.0, increment=0.1, textvariable=self.megapixels_var, width=10).grid(
            row=5, column=1, sticky=tk.W, pady=5, padx=5
        )
        
        # Options
        options_frame = ttk.Frame(settings_frame)
        options_frame.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=10)
        
        self.turbo_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Turbo Mode", variable=self.turbo_var).pack(side=tk.LEFT, padx=10)
        
        self.realism_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Realism LoRA", variable=self.realism_var).pack(side=tk.LEFT, padx=10)
        
        self.async_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Async Mode", variable=self.async_var).pack(side=tk.LEFT, padx=10)
        
        # Seed
        seed_frame = ttk.Frame(settings_frame)
        seed_frame.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=5)
        ttk.Label(seed_frame, text="Seed (optional):").pack(side=tk.LEFT, padx=5)
        self.seed_var = tk.StringVar()
        ttk.Entry(seed_frame, textvariable=self.seed_var, width=15).pack(side=tk.LEFT, padx=5)
        
        settings_frame.columnconfigure(1, weight=1)
        
        # Output Section
        output_frame = ttk.LabelFrame(main_frame, text="Output", padding="10")
        output_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(output_frame, text="Save to:").grid(row=0, column=0, sticky=tk.W, pady=5)
        output_path_frame = ttk.Frame(output_frame)
        output_path_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        self.output_path_var = tk.StringVar(value="output.mp4")
        ttk.Entry(output_path_frame, textvariable=self.output_path_var, width=45).pack(side=tk.LEFT, padx=5)
        ttk.Button(output_path_frame, text="Browse", command=self.browse_output).pack(side=tk.LEFT)
        
        output_frame.columnconfigure(1, weight=1)
        
        # Generate Button
        self.generate_btn = tk.Button(
            main_frame,
            text="🎬 Generate Video",
            command=self.generate_video,
            font=("Segoe UI", 12, "bold"),
            bg=self.button_color,
            fg=self.fg_color,
            activebackground=self.accent_color,
            activeforeground=self.fg_color,
            relief=tk.RAISED,
            bd=2,
            padx=20,
            pady=10,
            cursor="hand2"
        )
        self.generate_btn.grid(row=4, column=0, columnspan=2, pady=20)
        
        # Progress
        self.progress_var = tk.StringVar(value="Ready")
        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_var, font=("Segoe UI", 10))
        self.progress_label.grid(row=5, column=0, columnspan=2)
        
        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate', length=400)
        self.progress_bar.grid(row=6, column=0, columnspan=2, pady=10)
        
        # Log
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.grid(row=7, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=80, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(7, weight=1)
        
        self.log("Welcome to H3 Minimax Video Generator!")
        self.log("Please configure your RunPod API credentials above.")
    
    def log(self, message: str):
        """Add message to log."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def browse_image(self):
        """Browse for image file."""
        filetypes = (
            ("Image files", "*.png *.jpg *.jpeg *.webp"),
            ("All files", "*.*")
        )
        filename = filedialog.askopenfilename(title="Select Image", filetypes=filetypes)
        if filename:
            self.image_path_var.set(filename)
    
    def browse_output(self):
        """Browse for output file."""
        filename = filedialog.asksaveasfilename(
            title="Save Video As",
            defaultextension=".mp4",
            filetypes=(("MP4 files", "*.mp4"), ("All files", "*.*"))
        )
        if filename:
            self.output_path_var.set(filename)
    
    def load_config(self):
        """Load configuration from file."""
        config_file = Path.home() / ".h3minimax_config.json"
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                    self.api_key_var.set(config.get("api_key", ""))
                    self.endpoint_var.set(config.get("endpoint_id", ""))
                self.log("Configuration loaded from file.")
            except Exception as e:
                self.log(f"Error loading config: {e}")
    
    def save_config(self):
        """Save configuration to file."""
        config_file = Path.home() / ".h3minimax_config.json"
        try:
            config = {
                "api_key": self.api_key_var.get(),
                "endpoint_id": self.endpoint_var.get()
            }
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
            self.log("Configuration saved.")
            messagebox.showinfo("Success", "Configuration saved successfully!")
        except Exception as e:
            self.log(f"Error saving config: {e}")
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
    
    def generate_video(self):
        """Start video generation in background thread."""
        if self.is_generating:
            messagebox.showwarning("Busy", "Generation already in progress!")
            return
        
        # Validate inputs
        if not self.api_key_var.get() or not self.endpoint_var.get():
            messagebox.showerror("Error", "Please configure API Key and Endpoint ID!")
            return
        
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("Error", "Please enter a prompt!")
            return
        
        # Start generation in thread
        thread = threading.Thread(target=self._generate_video_thread, daemon=True)
        thread.start()
    
    def _generate_video_thread(self):
        """Background thread for video generation."""
        try:
            self.is_generating = True
            self.generate_btn.configure(state=tk.DISABLED, text="Generating...")
            self.progress_bar.start(10)
            self.progress_var.set("Initializing...")
            
            # Create client
            config = RunPodConfig(
                api_key=self.api_key_var.get(),
                endpoint_id=self.endpoint_var.get()
            )
            self.client = H3MinimaxClient(config)
            
            # Get parameters
            prompt = self.prompt_text.get("1.0", tk.END).strip()
            mode = self.mode_var.get()
            image_path = self.image_path_var.get() if self.image_path_var.get() else None
            output_path = self.output_path_var.get()
            
            # Parse seed
            seed = None
            if self.seed_var.get():
                try:
                    seed = int(self.seed_var.get())
                except ValueError:
                    pass
            
            self.log(f"\n{'='*60}")
            self.log(f"Starting generation...")
            self.log(f"Mode: {mode}")
            self.log(f"Prompt: {prompt}")
            self.log(f"Duration: {self.duration_var.get()}s")
            self.log(f"{'='*60}\n")
            
            self.progress_var.set("Generating video...")
            
            # Generate
            kwargs = {
                "duration": self.duration_var.get(),
                "aspect_ratio": self.aspect_var.get(),
                "megapixels": self.megapixels_var.get(),
                "turbo_mode": self.turbo_var.get(),
                "realism_lora": self.realism_var.get(),
                "async_mode": self.async_var.get()
            }
            
            if seed is not None:
                kwargs["seed"] = seed
            
            if mode == "i2v" and image_path:
                kwargs["image_path"] = image_path
            elif mode == "r2v" and image_path:
                # For simplicity, treat as single reference
                kwargs["reference_images"] = [image_path]
            
            result_path = self.client.generate_video(
                prompt=prompt,
                output_path=output_path,
                mode=mode,
                **kwargs
            )
            
            self.progress_var.set("Complete!")
            self.log(f"\n✅ Video saved to: {result_path}")
            
            # Show success dialog
            self.root.after(0, lambda: messagebox.showinfo(
                "Success",
                f"Video generated successfully!\n\nSaved to: {result_path}"
            ))
            
            # Offer to open
            if messagebox.askyesno("Open Video", "Would you like to open the video?"):
                webbrowser.open(f"file://{os.path.abspath(result_path)}")
            
        except Exception as e:
            self.log(f"\n❌ Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Error", f"Generation failed:\n\n{e}"))
        
        finally:
            self.is_generating = False
            self.progress_bar.stop()
            self.generate_btn.configure(state=tk.NORMAL, text="🎬 Generate Video")
            self.progress_var.set("Ready")


def main():
    """Run the GUI application."""
    root = tk.Tk()
    app = H3MinimaxGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
