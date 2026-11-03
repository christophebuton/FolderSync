#!/usr/bin/env python3
"""
Script de synchronisation Dossier vers Dossier
Application Tkinter avec interface graphique pour synchroniser des dossiers via rsync
"""

import sys
import subprocess
import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class SyncWindow(tk.Tk):
    """
    Fenêtre principale de l'application de synchronisation
    Utilise Tkinter pour une interface légère et compatible.
    """
    
    def __init__(self):
        """Constructeur - Initialise la fenêtre et charge la configuration"""
        super().__init__()
        
        # Configuration de la fenêtre principale
        self.title("Synchronisation Dossier → Dossier")
        self.geometry("800x600")
        self.minsize(600, 480)
        
        # Chargement de l'icône foldersync.png dans le même répertoire que le script
        script_dir = os.path.dirname(os.path.realpath(__file__))
        icon_path = os.path.join(script_dir, "foldersync.png")
        if os.path.exists(icon_path):
            try:
                self.icon_image = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, self.icon_image)
            except Exception as e:
                print(f"Impossible de charger l'icône : {e}")
        
        # Style ttk
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        
        # Configuration globale des polices en taille 12
        self.style.configure('.', font=('Helvetica', 12))
        self.style.configure('TButton', font=('Helvetica', 12, 'bold'), padding=8)
        self.style.configure('TLabel', font=('Helvetica', 12))
        
        # Chemin de configuration
        self.config_path = os.path.expanduser("~/.config/folder_sync/chemins.json")
        
        # Variable pour contrôler le processus rsync
        self.current_process = None
        
        # Chargement de la configuration
        self.source_dir, self.dest_dir = self.load_config()
        
        # Interface utilisateur
        self.init_ui()

    def init_ui(self):
        """Initialise l'interface utilisateur"""
        
        # Conteneur principal avec marges
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === SECTION SOURCE ===
        source_frame = ttk.Frame(main_frame)
        source_frame.pack(fill=tk.X, pady=6)
        
        ttk.Label(source_frame, text="Source :", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        
        self.source_path_var = tk.StringVar(value=self.source_dir)
        self.source_path_label = ttk.Label(source_frame, textvariable=self.source_path_var, relief="sunken", anchor="w")
        self.source_path_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.source_status_label = tk.Label(source_frame, text="", font=('Helvetica', 14, 'bold'))
        self.source_status_label.pack(side=tk.LEFT, padx=5)
        
        self.source_button = ttk.Button(source_frame, text="Parcourir...", command=self.select_source)
        self.source_button.pack(side=tk.RIGHT)
        
        # Vérification existence source
        source_exists = os.path.exists(self.source_dir) if self.source_dir else False
        self.update_status(self.source_status_label, source_exists)

        # === SECTION DESTINATION ===
        dest_frame = ttk.Frame(main_frame)
        dest_frame.pack(fill=tk.X, pady=6)
        
        ttk.Label(dest_frame, text="Destination :", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        
        self.dest_path_var = tk.StringVar(value=self.dest_dir)
        self.dest_path_label = ttk.Label(dest_frame, textvariable=self.dest_path_var, relief="sunken", anchor="w")
        self.dest_path_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.dest_status_label = tk.Label(dest_frame, text="", font=('Helvetica', 14, 'bold'))
        self.dest_status_label.pack(side=tk.LEFT, padx=5)
        
        self.dest_button = ttk.Button(dest_frame, text="Parcourir...", command=self.select_dest)
        self.dest_button.pack(side=tk.RIGHT)
        
        # Vérification existence destination
        dest_exists = os.path.exists(self.dest_dir) if self.dest_dir else False
        self.update_status(self.dest_status_label, dest_exists)

        # === AVERTISSEMENT SYSTEME DE FICHIERS / CARACTERES INTERDITS ===
        self.fs_warning_var = tk.StringVar(value="")
        self.fs_warning_label = tk.Label(
            main_frame, textvariable=self.fs_warning_var, 
            font=('Helvetica', 11, 'bold'), fg="#d9534f", justify=tk.LEFT
        )
        self.fs_warning_label.pack(fill=tk.X, pady=4)
        
        # Vérification initiale si la destination configurée existe
        if dest_exists:
            self.check_destination_fs(self.dest_dir)

        # === BOUTONS D'ACTION (3 boutons de largeur égale via grid) ===
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=10)
        
        action_frame.grid_columnconfigure(0, weight=1)
        action_frame.grid_columnconfigure(1, weight=1)
        action_frame.grid_columnconfigure(2, weight=1)
        
        button_font = ('Helvetica', 12, 'bold')
        
        # Bouton de test (Vert)
        self.test_button = tk.Button(
            action_frame, text="Tester la synchronisation", command=self.test_sync,
            bg="#4CAF50", fg="white", activebackground="#45a049", activeforeground="white",
            relief="raised", bd=2, font=button_font, pady=11
        )
        self.test_button.grid(row=0, column=0, padx=4, sticky="ew")
        
        # Bouton de synchronisation (Bleu)
        self.sync_button = tk.Button(
            action_frame, text="Lancer la synchronisation", command=self.run_sync,
            bg="#2196F3", fg="white", activebackground="#0b7dda", activeforeground="white",
            relief="raised", bd=2, font=button_font, pady=11
        )
        self.sync_button.grid(row=0, column=1, padx=4, sticky="ew")
        
        # Bouton d'annulation (Rouge)
        self.cancel_button = tk.Button(
            action_frame, text="Annuler", command=self.cancel_sync, state=tk.DISABLED,
            bg="#f44336", fg="white", activebackground="#da190b", activeforeground="white",
            relief="raised", bd=2, font=button_font, pady=11
        )
        self.cancel_button.grid(row=0, column=2, padx=4, sticky="ew")

        # === ZONE DE SORTIE (POLICE TAILLE 12) ===
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.text_edit = tk.Text(
            text_frame, bg="black", fg="#e0e0e0", font=("Monospace", 12),
            wrap=tk.WORD, insertbackground="white"
        )
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_edit.yview)
        self.text_edit.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_edit.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configuration des tags de couleurs dans la zone de texte
        self.text_edit.tag_config("green", foreground="#4CAF50")
        self.text_edit.tag_config("blue", foreground="#2196F3")
        self.text_edit.tag_config("red", foreground="#f44336")

        # === BOUTON FERMER ===
        self.close_button = ttk.Button(main_frame, text="Fermer", command=self.destroy)
        self.close_button.pack(side=tk.BOTTOM, anchor="e", pady=(10, 0))

    def update_status(self, status_label, exists):
        """Met à jour l'indicateur de statut"""
        if exists:
            status_label.config(text="✅", fg="green")
        else:
            status_label.config(text="❌", fg="red")

    def check_destination_fs(self, path):
        """Détecte si le système de fichiers de la destination est exfat, fat ou ntfs"""
        if not path or not os.path.exists(path):
            self.fs_warning_var.set("")
            return
        
        fs_type = "inconnu"
        try:
            # Commande système pour identifier le type de partition sous Linux
            res = subprocess.run(["df", "-T", path], capture_output=True, text=True, check=True)
            lines = res.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 2:
                    fs_type = parts[1].lower()
        except Exception:
            pass
        
        # Formats visés par l'avertissement
        restricted_fs = ["fat", "vfat", "fat32", "exfat", "ntfs", "fuseblk"]
        
        is_restricted = any(fs in fs_type for fs in restricted_fs)
        
        if is_restricted:
            chars = '<  >  :  "  /  \  |  ?  *'
            msg = f"⚠️ Système détecté : {fs_type.upper()} — Caractères incompatibles : {chars}"
            self.fs_warning_var.set(msg)
        else:
            self.fs_warning_var.set("")

    def load_config(self):
        """Charge la configuration depuis le fichier JSON"""
        default_source = ""
        default_dest = ""
        
        config_dir = os.path.dirname(self.config_path)
        os.makedirs(config_dir, exist_ok=True)
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                    source = config.get("source_dir", default_source)
                    dest = config.get("dest_dir", default_dest)
                    
                    if source and source.endswith("/") and source != "/":
                        source = source[:-1]
                    if dest and dest.endswith("/") and dest != "/":
                        dest = dest[:-1]
                    
                    return source, dest
            except (json.JSONDecodeError, IOError):
                pass
        
        return default_source, default_dest

    def save_config(self):
        """Sauvegarde la configuration"""
        config = {
            "source_dir": self.source_dir,
            "dest_dir": self.dest_dir
        }
        try:
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)
        except IOError:
            pass

    def select_source(self):
        """Sélection du dossier source - démarre dans le home utilisateur"""
        start_dir = os.path.expanduser("~")
        
        dir_path = filedialog.askdirectory(
            title="Sélectionner le répertoire source",
            initialdir=start_dir
        )
        
        if dir_path:
            self.source_dir = dir_path
            self.source_path_var.set(self.source_dir)
            self.update_status(self.source_status_label, True)
            self.save_config()

    def select_dest(self):
        """Sélection du dossier destination - démarre dans /media"""
        username = os.getenv('USER', 'user')
        start_dir = f"/media/{username}"
        
        if not os.path.exists(start_dir):
            start_dir = "/media"
        if not os.path.exists(start_dir):
            start_dir = os.path.expanduser("~")
        
        dir_path = filedialog.askdirectory(
            title="Sélectionner le répertoire de destination",
            initialdir=start_dir
        )
        
        if dir_path:
            self.dest_dir = dir_path
            self.dest_path_var.set(self.dest_dir)
            self.update_status(self.dest_status_label, True)
            self.check_destination_fs(self.dest_dir)
            self.save_config()

    def append_colored_text(self, text, tag):
        """Ajoute du texte coloré à la zone de sortie"""
        self.text_edit.insert(tk.END, text, tag)
        self.text_edit.see(tk.END)

    def set_buttons_during_operation(self, running):
        """Active/désactive les boutons pendant une opération"""
        if running:
            self.test_button.config(state=tk.DISABLED)
            self.sync_button.config(state=tk.DISABLED)
            self.cancel_button.config(state=tk.NORMAL)
            self.source_button.config(state=tk.DISABLED)
            self.dest_button.config(state=tk.DISABLED)
        else:
            self.test_button.config(state=tk.NORMAL)
            self.sync_button.config(state=tk.NORMAL)
            self.cancel_button.config(state=tk.DISABLED)
            self.source_button.config(state=tk.NORMAL)
            self.dest_button.config(state=tk.NORMAL)

    def check_folders(self):
        """Vérifie l'existence des dossiers avant opération"""
        source_exists = os.path.exists(self.source_dir) if self.source_dir else False
        dest_exists = os.path.exists(self.dest_dir) if self.dest_dir else False
        
        self.update_status(self.source_status_label, source_exists)
        self.update_status(self.dest_status_label, dest_exists)
        
        if not source_exists:
            self.append_colored_text("❌ Le dossier source n'existe pas ou n'est pas valide.\n", "red")
            return False
        
        if not dest_exists:
            self.append_colored_text("❌ Le dossier de destination n'existe pas ou n'est pas valide.\n", "red")
            return False
        
        return True

    def test_sync(self):
        """Lance un test de synchronisation (dry-run)"""
        if not self.check_folders():
            return

        self.text_edit.delete("1.0", tk.END)
        self.append_colored_text("=== MODE TEST - Aucune modification ne sera effectuée ===\n", "green")
        self.text_edit.insert(tk.END, f"Test de synchronisation de {self.source_dir} vers {self.dest_dir}\n")

        self.set_buttons_during_operation(True)

        self.current_process = subprocess.Popen(
            ["rsync", "-r", "-t", "-v", "--progress", "--delete", "-u", "--modify-window=1", "--dry-run",
             self.source_dir + "/", self.dest_dir + "/"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )

        try:
            for line in self.current_process.stdout:
                if self.current_process.poll() is None:
                    self.text_edit.insert(tk.END, line)
                    self.text_edit.see(tk.END)
                    self.update()
                else:
                    break

            self.current_process.wait()
            
            if self.current_process.returncode == 0:
                self.append_colored_text("\n--- Test terminé - Aucune modification effectuée ---\n", "green")
            else:
                self.append_colored_text("\n--- Test interrompu ---\n", "red")
                
        except Exception as e:
            self.append_colored_text(f"\n--- Erreur pendant le test : {str(e)} ---\n", "red")
        
        finally:
            self.current_process = None
            self.set_buttons_during_operation(False)

    def run_sync(self):
        """Lance la synchronisation réelle"""
        if not self.check_folders():
            return

        self.text_edit.delete("1.0", tk.END)
        self.append_colored_text("=== SYNCHRONISATION RÉELLE ===\n", "blue")
        self.text_edit.insert(tk.END, f"Lancement de la synchronisation de {self.source_dir} vers {self.dest_dir}\n")

        self.set_buttons_during_operation(True)

        self.current_process = subprocess.Popen(
            ["rsync", "-r", "-t", "-v", "--progress", "--delete", "-u", "--modify-window=1",
             self.source_dir + "/", self.dest_dir + "/"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )

        try:
            for line in self.current_process.stdout:
                if self.current_process.poll() is None:
                    self.text_edit.insert(tk.END, line)
                    self.text_edit.see(tk.END)
                    self.update()
                else:
                    break

            self.current_process.wait()
            
            if self.current_process.returncode == 0:
                self.append_colored_text("\n--- Synchronisation terminée ---\n", "blue")
            else:
                self.append_colored_text("\n--- Synchronisation interrompue ---\n", "red")
                
        except Exception as e:
            self.append_colored_text(f"\n--- Erreur pendant la synchronisation : {str(e)} ---\n", "red")
        
        finally:
            self.current_process = None
            self.set_buttons_during_operation(False)

    def cancel_sync(self):
        """Annule la synchronisation en cours"""
        if self.current_process and self.current_process.poll() is None:
            self.append_colored_text("\n--- Annulation en cours... ---\n", "red")
            self.current_process.terminate()
            
            try:
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
                self.current_process.wait()
            
            self.append_colored_text("--- Opération annulée ---\n", "red")
            self.current_process = None
            self.set_buttons_during_operation(False)


if __name__ == "__main__":
    app = SyncWindow()
    app.mainloop()
