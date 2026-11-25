#!/usr/bin/env python3
"""
Synchronisation Dossier → Dossier

Application Tkinter (widgets ttk autant que possible) qui synchronise un
dossier source vers un dossier destination via rsync.

Fonctionnement général :
  - les chemins source/destination sont mémorisés dans un fichier JSON ;
  - un test (« dry-run ») permet de prévisualiser les changements ;
  - rsync tourne dans un thread séparé : l'interface reste réactive et le
    bouton « Annuler » fonctionne pendant l'opération ;
  - si la destination est en FAT/exFAT/NTFS, un avertissement liste les
    caractères interdits dans les noms de fichiers.
"""

import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, ttk

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

CONFIG_PATH = os.path.expanduser("~/.config/folder_sync/chemins.json")

# Options rsync communes au test et à la synchronisation réelle :
#   -r recursif, -t conserve les dates, -v verbeux, --progress progression,
#   --delete supprime à la destination ce qui n'existe plus à la source,
#   -u ne remplace pas un fichier plus récent à la destination,
#   --modify-window=1 tolère 1 s d'écart (FAT arrondit les dates à 2 s).
RSYNC_OPTIONS = ["-r", "-t", "-v", "--progress", "--delete", "-u", "--modify-window=1"]

# Systèmes de fichiers qui imposent des restrictions sur les noms de fichiers
RESTRICTED_FS = ("fat", "vfat", "fat32", "exfat", "ntfs", "fuseblk")

# Caractères interdits sur ces systèmes de fichiers
FORBIDDEN_CHARS = '<  >  :  "  /  \\  |  ?  *'

# Couleurs des boutons d'action : (normal, survol)
BUTTON_COLORS = {
    "Test": ("#4CAF50", "#45a049"),    # vert
    "Sync": ("#2196F3", "#0b7dda"),    # bleu
    "Cancel": ("#f44336", "#da190b"),  # rouge
}

FONT = ("Helvetica", 12)
FONT_BOLD = ("Helvetica", 12, "bold")


class SyncWindow(tk.Tk):
    """Fenêtre principale de l'application."""

    def __init__(self):
        super().__init__()

        # --- Fenêtre ---
        self.title("Synchronisation Dossier → Dossier")
        self.geometry("800x600")
        self.minsize(600, 480)
        self._load_icon()
        self._setup_styles()

        # --- État interne ---
        self.current_process = None        # processus rsync en cours (ou None)
        self.output_queue = queue.Queue()  # lignes envoyées par le thread lecteur
        self.cancelled = False             # True si l'utilisateur a annulé

        # --- Configuration et variables liées aux widgets ---
        source, dest = self.load_config()
        self.source_var = tk.StringVar(value=source)
        self.dest_var = tk.StringVar(value=dest)
        self.fs_warning_var = tk.StringVar()

        # --- Interface ---
        self.build_ui()

        # Vérifications initiales (indicateurs ✅/❌ et avertissement FS)
        self.update_status(self.source_status, source)
        self.update_status(self.dest_status, dest)
        self.check_destination_fs(dest)

    # ======================================================================
    # Initialisation : icône et styles
    # ======================================================================

    def _load_icon(self):
        """Charge foldersync.png (placé à côté du script) comme icône."""
        script_dir = os.path.dirname(os.path.realpath(__file__))
        icon_path = os.path.join(script_dir, "foldersync.png")
        if not os.path.exists(icon_path):
            return
        try:
            # On garde une référence : sinon l'image est détruite par Python
            self.icon_image = tk.PhotoImage(file=icon_path)
            self.iconphoto(True, self.icon_image)
        except tk.TclError as e:
            print(f"Impossible de charger l'icône : {e}")

    def _setup_styles(self):
        """Configure le thème ttk et les styles personnalisés."""
        style = ttk.Style(self)
        style.theme_use("clam")  # thème qui accepte les couleurs de fond

        # Police par défaut de tous les widgets ttk
        style.configure(".", font=FONT)
        # Boutons standards (« Parcourir... », « Fermer ») : même compensation
        # verticale que les boutons d'action (10 en haut, 6 en bas, somme 16)
        style.configure("TButton", font=FONT_BOLD, anchor="center",
                        padding=(8, 10, 8, 6))
        style.configure("Bold.TLabel", font=FONT_BOLD)
        style.configure("Path.TLabel", relief="sunken", padding=3)
        style.configure("Warning.TLabel", font=("Helvetica", 11, "bold"),
                        foreground="#d9534f")
        style.configure("Status.TLabel", font=("Helvetica", 14, "bold"))

        # Boutons colorés : un style par bouton d'action
        for name, (normal, hover) in BUTTON_COLORS.items():
            style_name = f"{name}.TButton"
            # padding = (gauche, haut, droite, bas). Les polices ont souvent
            # plus d'espace sous la ligne que dessus : le texte paraît alors
            # trop haut. On compense avec plus de marge en haut qu'en bas.
            # Ajustez les valeurs 13 / 9 (leur somme doit rester à 22).
            style.configure(style_name, background=normal, foreground="white",
                            anchor="center", padding=(8, 13, 8, 9))
            style.map(
                style_name,
                background=[("disabled", "#b0b0b0"), ("active", hover)],
                foreground=[("disabled", "#eeeeee")],
            )

    # ======================================================================
    # Construction de l'interface
    # ======================================================================

    def build_ui(self):
        """Construit tous les widgets de la fenêtre."""
        main = ttk.Frame(self, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Lignes « Source » et « Destination » (même construction)
        self.source_status, self.source_button = self._build_path_row(
            main, "Source :", self.source_var, self.select_source)
        self.dest_status, self.dest_button = self._build_path_row(
            main, "Destination :", self.dest_var, self.select_dest)

        # Avertissement sur le système de fichiers de la destination
        ttk.Label(main, textvariable=self.fs_warning_var,
                  style="Warning.TLabel", justify=tk.LEFT).pack(fill=tk.X, pady=4)

        self._build_action_buttons(main)
        self._build_output_area(main)

        # Bouton Fermer, en bas à droite
        ttk.Button(main, text="Fermer", command=self.destroy).pack(
            side=tk.BOTTOM, anchor="e", pady=(10, 0))

    def _build_path_row(self, parent, label, variable, command):
        """
        Construit une ligne : libellé | chemin | indicateur | bouton Parcourir.
        Retourne (label_indicateur, bouton) pour pouvoir les modifier ensuite.
        """
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=6)

        ttk.Label(row, text=label, style="Bold.TLabel").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(row, textvariable=variable, style="Path.TLabel", anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        status = ttk.Label(row, style="Status.TLabel")
        status.pack(side=tk.LEFT, padx=5)

        button = ttk.Button(row, text="Parcourir...", command=command)
        button.pack(side=tk.RIGHT)
        return status, button

    def _build_action_buttons(self, parent):
        """Construit les trois boutons d'action de largeur égale (grille)."""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=10)

        buttons = (
            ("test_button", "Tester la synchronisation", "Test", self.test_sync),
            ("sync_button", "Lancer la synchronisation", "Sync", self.run_sync),
            ("cancel_button", "Annuler", "Cancel", self.cancel_sync),
        )
        for col, (attr, text, style_prefix, command) in enumerate(buttons):
            frame.columnconfigure(col, weight=1)  # colonnes de largeur égale
            button = ttk.Button(frame, text=text, command=command,
                                style=f"{style_prefix}.TButton")
            button.grid(row=0, column=col, padx=4, sticky="ew")
            setattr(self, attr, button)

        # « Annuler » n'a de sens que pendant une opération
        self.cancel_button.state(["disabled"])

    def _build_output_area(self, parent):
        """Construit la zone de sortie (seul widget non-ttk : ttk n'a pas de Text)."""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.text_edit = tk.Text(frame, bg="black", fg="#e0e0e0",
                                 font=("Monospace", 12), wrap=tk.WORD,
                                 insertbackground="white")
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                  command=self.text_edit.yview)
        self.text_edit.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_edit.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Étiquettes de couleur utilisables à l'insertion de texte
        for tag, color in (("green", "#4CAF50"), ("blue", "#2196F3"),
                           ("red", "#f44336")):
            self.text_edit.tag_config(tag, foreground=color)

    # ======================================================================
    # Configuration (fichier JSON)
    # ======================================================================

    @staticmethod
    def _strip_trailing_slash(path):
        """Retire le « / » final d'un chemin (sauf pour la racine « / »)."""
        return path[:-1] if path.endswith("/") and path != "/" else path

    def load_config(self):
        """Retourne (source, destination) lus dans le fichier JSON."""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError):
            return "", ""  # fichier absent ou corrompu : valeurs vides

        return (self._strip_trailing_slash(config.get("source_dir", "")),
                self._strip_trailing_slash(config.get("dest_dir", "")))

    def save_config(self):
        """Enregistre les chemins courants dans le fichier JSON."""
        config = {"source_dir": self.source_var.get(),
                  "dest_dir": self.dest_var.get()}
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
        except OSError:
            pass  # l'échec de sauvegarde n'est pas bloquant

    # ======================================================================
    # Sélection des dossiers
    # ======================================================================

    def select_source(self):
        """Choisit le dossier source (la boîte s'ouvre dans le home)."""
        path = filedialog.askdirectory(
            title="Sélectionner le répertoire source",
            initialdir=os.path.expanduser("~"))
        if path:
            self.source_var.set(path)
            self.update_status(self.source_status, path)
            self.save_config()

    def select_dest(self):
        """Choisit le dossier destination (la boîte s'ouvre dans /media)."""
        # Premier dossier existant parmi : /media/<user>, /media, ~
        candidates = (f"/media/{os.getenv('USER', 'user')}", "/media",
                      os.path.expanduser("~"))
        start_dir = next((d for d in candidates if os.path.exists(d)), "~")

        path = filedialog.askdirectory(
            title="Sélectionner le répertoire de destination",
            initialdir=start_dir)
        if path:
            self.dest_var.set(path)
            self.update_status(self.dest_status, path)
            self.check_destination_fs(path)
            self.save_config()

    # ======================================================================
    # Indicateurs et vérifications
    # ======================================================================

    @staticmethod
    def update_status(status_label, path):
        """Affiche ✅ (vert) si le chemin existe, ❌ (rouge) sinon."""
        if path and os.path.exists(path):
            status_label.config(text="✅", foreground="green")
        else:
            status_label.config(text="❌", foreground="red")

    def check_destination_fs(self, path):
        """Affiche un avertissement si la destination est en FAT/exFAT/NTFS."""
        self.fs_warning_var.set("")
        if not path or not os.path.exists(path):
            return

        # `df -T` affiche le type de système de fichiers (2e colonne, 2e ligne)
        try:
            result = subprocess.run(["df", "-T", path], capture_output=True,
                                    text=True, check=True)
            fs_type = result.stdout.strip().split("\n")[1].split()[1].lower()
        except (subprocess.SubprocessError, OSError, IndexError):
            return  # type indéterminé : pas d'avertissement

        if any(fs in fs_type for fs in RESTRICTED_FS):
            self.fs_warning_var.set(
                f"⚠️ Système détecté : {fs_type.upper()} — "
                f"Caractères incompatibles : {FORBIDDEN_CHARS}")

    def check_folders(self):
        """Vérifie que source et destination existent avant une opération."""
        ok = True
        for var, status, name in (
                (self.source_var, self.source_status, "source"),
                (self.dest_var, self.dest_status, "de destination")):
            path = var.get()
            self.update_status(status, path)
            if not (path and os.path.exists(path)):
                self.append_text(
                    f"❌ Le dossier {name} n'existe pas ou n'est pas valide.\n",
                    "red")
                ok = False
        return ok

    # ======================================================================
    # Affichage et état des boutons
    # ======================================================================

    def append_text(self, text, tag=None):
        """Ajoute du texte (éventuellement coloré) en bas de la zone de sortie."""
        self.text_edit.insert(tk.END, text, tag)
        self.text_edit.see(tk.END)

    def set_running(self, running):
        """Active/désactive les contrôles selon qu'une opération est en cours."""
        for widget in (self.test_button, self.sync_button,
                       self.source_button, self.dest_button):
            widget.state(["disabled"] if running else ["!disabled"])
        self.cancel_button.state(["!disabled"] if running else ["disabled"])

    # ======================================================================
    # Exécution de rsync
    # ======================================================================

    def test_sync(self):
        """Simulation (--dry-run) : rien n'est modifié."""
        self.start_rsync(dry_run=True)

    def run_sync(self):
        """Synchronisation réelle."""
        self.start_rsync(dry_run=False)

    def start_rsync(self, dry_run):
        """Lance rsync dans un thread et affiche sa sortie au fil de l'eau."""
        if not self.check_folders():
            return

        source, dest = self.source_var.get(), self.dest_var.get()

        # En-tête affiché selon le mode
        self.text_edit.delete("1.0", tk.END)
        if dry_run:
            self.append_text("=== MODE TEST - Aucune modification ne sera "
                             "effectuée ===\n", "green")
            self.append_text(f"Test de synchronisation de {source} vers {dest}\n")
        else:
            self.append_text("=== SYNCHRONISATION RÉELLE ===\n", "blue")
            self.append_text(f"Lancement de la synchronisation de {source} "
                             f"vers {dest}\n")

        # Le « / » final force rsync à copier le CONTENU du dossier source
        command = ["rsync", *RSYNC_OPTIONS]
        if dry_run:
            command.append("--dry-run")
        command += [source + "/", dest + "/"]

        self.set_running(True)
        self.cancelled = False

        try:
            self.current_process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True)
        except OSError as e:  # par ex. rsync non installé
            self.append_text(f"\n--- Impossible de lancer rsync : {e} ---\n", "red")
            self.set_running(False)
            return

        # Thread lecteur : il évite de bloquer l'interface sur la lecture
        # de la sortie. Il transmet les lignes via la file `output_queue`.
        threading.Thread(target=self._read_output,
                         args=(self.current_process,), daemon=True).start()

        # Tkinter n'est pas thread-safe : seul le thread principal touche aux
        # widgets. On vide donc la file périodiquement avec `after`.
        self.after(50, self._poll_output, dry_run)

    def _read_output(self, process):
        """(Thread secondaire) Lit la sortie de rsync ligne par ligne."""
        for line in process.stdout:
            self.output_queue.put(line)
        self.output_queue.put(None)  # None = fin de la sortie

    def _poll_output(self, dry_run):
        """(Thread principal) Affiche les lignes reçues, puis conclut."""
        finished = False
        try:
            while True:
                line = self.output_queue.get_nowait()
                if line is None:
                    finished = True
                    break
                self.append_text(line)
        except queue.Empty:
            pass  # file vide pour l'instant

        if finished:
            self._finish(dry_run)
        else:
            self.after(50, self._poll_output, dry_run)  # on repasse plus tard

    def _finish(self, dry_run):
        """Affiche le message de fin selon le code retour de rsync."""
        process, self.current_process = self.current_process, None
        returncode = process.wait()

        if self.cancelled:
            self.append_text("--- Opération annulée ---\n", "red")
        elif returncode == 0:
            if dry_run:
                self.append_text("\n--- Test terminé - Aucune modification "
                                 "effectuée ---\n", "green")
            else:
                self.append_text("\n--- Synchronisation terminée ---\n", "blue")
        else:
            label = "Test interrompu" if dry_run else "Synchronisation interrompue"
            self.append_text(f"\n--- {label} ---\n", "red")

        self.set_running(False)

    def cancel_sync(self):
        """Interrompt rsync ; _poll_output/_finish se chargent du reste."""
        process = self.current_process
        if process and process.poll() is None:
            self.cancelled = True
            self.append_text("\n--- Annulation en cours... ---\n", "red")
            process.terminate()  # arrêt poli (SIGTERM)
            # Si rsync ne réagit pas sous 5 s, on force l'arrêt (SIGKILL)
            self.after(5000, lambda: process.poll() is None and process.kill())


if __name__ == "__main__":
    SyncWindow().mainloop()
