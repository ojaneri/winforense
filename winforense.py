#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
winforense.py

Ferramenta básica de análise forense em Windows, focada em:
- Informações de sistema
- Histórico de navegação (browsers principais)
- Programas instalados
- Arquivos da Lixeira ($Recycle.Bin)
- Hardware bruto (via WMIC)
- Discos lógicos (C:, D:, etc.)
- Histórico de dispositivos USB de armazenamento (USBSTOR)
- Geração de relatório HTML com abas e timeline consolidada

Projeto para fins didáticos/forenses, uso em ambiente autorizado.
Créditos: Osvaldo Janeri Filho - https://instagram.com/peritosegurancadainformacao
"""

import os
import sys
import shutil
import sqlite3
import tempfile
import struct
import subprocess
import string
from datetime import datetime, timedelta, timezone
import getpass
import socket
import platform

try:
    import winreg  # type: ignore
except ImportError:
    winreg = None

# ---------------------------
# CONSTANTES E HELPERS DE TEMPO
# ---------------------------

EPOCH_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)


def chrome_time_to_dt(chrome_time):
    """
    Converte timestamp do Chrome (microsegundos desde 1601-01-01) para datetime.
    """
    try:
        if chrome_time is None:
            return None
        return EPOCH_1601 + timedelta(microseconds=int(chrome_time))
    except Exception:
        return None


def unix_micro_to_dt(unix_micro):
    """
    Converte timestamp em micros desde 1970 para datetime.
    Usado no Firefox (moz_historyvisits.visit_date).
    """
    try:
        if unix_micro is None:
            return None
        return datetime.fromtimestamp(unix_micro / 1_000_000, tz=timezone.utc)
    except Exception:
        return None


def filetime_to_dt(filetime):
    """
    Converte FILETIME (intervalos de 100ns desde 1601-01-01) para datetime.
    """
    try:
        if not filetime:
            return None
        microseconds = filetime / 10  # 100ns -> microsegundos
        return EPOCH_1601 + timedelta(microseconds=microseconds)
    except Exception:
        return None


# ---------------------------
# INFORMAÇÕES DE SISTEMA
# ---------------------------

def get_system_info():
    """
    Coleta informações básicas de sistema.
    """
    try:
        info = {
            "hostname": socket.gethostname(),
            "ip": None,
            "user": getpass.getuser(),
            "os": platform.system(),
            "os_version": platform.version(),
            "release": platform.release(),
            "machine": platform.machine(),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            info["ip"] = socket.gethostbyname(info["hostname"])
        except Exception:
            info["ip"] = "desconhecido"
        return info
    except Exception as e:
        return {"error": str(e)}


# ---------------------------
# FUNÇÕES AUXILIARES PARA SQLITE
# ---------------------------

def copy_sqlite_db(src_path, label):
    """
    Copia o arquivo SQLite para uma pasta temporária, evitando
    conflito com o browser rodando.
    """
    try:
        if not os.path.exists(src_path):
            return None
        tmp_dir = tempfile.gettempdir()
        base_name = f"winforense_{label}_{os.path.basename(src_path)}"
        dst_path = os.path.join(tmp_dir, base_name)
        shutil.copy2(src_path, dst_path)
        return dst_path
    except Exception:
        return None


# ---------------------------
# HISTÓRICO DE NAVEGAÇÃO (CHROMIUM + FIREFOX)
# ---------------------------

def fetch_chromium_history(db_path, browser_name, events):
    """
    Lê histórico de um browser Chromium-like (Chrome, Edge, Brave, Opera).
    Usa a tabela 'urls' para coletar últimos registros.
    """
    copied = copy_sqlite_db(db_path, browser_name.lower())
    if not copied:
        return

    try:
        conn = sqlite3.connect(copied)
        cur = conn.cursor()
        query = """
        SELECT 
            urls.url,
            urls.title,
            urls.visit_count,
            urls.typed_count,
            urls.last_visit_time
        FROM urls
        ORDER BY last_visit_time DESC
        LIMIT 500
        """
        for row in cur.execute(query):
            url, title, visit_count, typed_count, last_visit_time = row
            dt = chrome_time_to_dt(last_visit_time)
            if dt is None:
                continue
            events.append({
                "timestamp": dt,
                "category": "browser",
                "source": browser_name,
                "title": title or url or "(sem título)",
                "details": f"URL: {url}<br>Visitas: {visit_count} | Digitado: {typed_count}"
            })
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            os.remove(copied)
        except Exception:
            pass


def fetch_firefox_history(events):
    """
    Lê histórico básico do Firefox (primeiro perfil encontrado).
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return

    profiles_dir = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
    if not os.path.isdir(profiles_dir):
        return

    profile_dirs = [d for d in os.listdir(profiles_dir)
                    if os.path.isdir(os.path.join(profiles_dir, d))]
    if not profile_dirs:
        return

    profile_path = os.path.join(profiles_dir, profile_dirs[0])
    db_path = os.path.join(profile_path, "places.sqlite")
    copied = copy_sqlite_db(db_path, "firefox")
    if not copied:
        return

    try:
        conn = sqlite3.connect(copied)
        cur = conn.cursor()
        query = """
        SELECT 
            moz_places.url,
            moz_places.title,
            moz_places.visit_count,
            moz_historyvisits.visit_date
        FROM moz_places
        JOIN moz_historyvisits
          ON moz_places.id = moz_historyvisits.place_id
        ORDER BY moz_historyvisits.visit_date DESC
        LIMIT 500
        """
        for row in cur.execute(query):
            url, title, visit_count, visit_date = row
            dt = unix_micro_to_dt(visit_date)
            if dt is None:
                continue
            events.append({
                "timestamp": dt,
                "category": "browser",
                "source": "Firefox",
                "title": title or url or "(sem título)",
                "details": f"URL: {url}<br>Visitas: {visit_count}"
            })
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            os.remove(copied)
        except Exception:
            pass


def collect_browser_histories(events):
    """
    Coleta históricos dos principais browsers instalados.
    """
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        paths = {
            "Chrome": os.path.join(localapp, "Google", "Chrome", "User Data", "Default", "History"),
            "Edge": os.path.join(localapp, "Microsoft", "Edge", "User Data", "Default", "History"),
            "Brave": os.path.join(localapp, "BraveSoftware", "Brave-Browser", "User Data", "Default", "History"),
            "Opera": os.path.join(localapp, "Opera Software", "Opera Stable", "History"),
        }

        for name, path in paths.items():
            fetch_chromium_history(path, name, events)

    fetch_firefox_history(events)


# ---------------------------
# PROGRAMAS INSTALADOS (REGISTRO)
# ---------------------------

def get_installed_programs():
    """
    Lê programas instalados a partir do Registro.
    """
    programs = []
    if winreg is None:
        return programs

    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hive, subkey in reg_paths:
        try:
            key = winreg.OpenKey(hive, subkey)
        except Exception:
            continue

        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break

            try:
                sk = winreg.OpenKey(key, subkey_name)
                name, version, publisher, install_date = None, None, None, None

                try:
                    name = winreg.QueryValueEx(sk, "DisplayName")[0]
                except Exception:
                    pass
                if not name:
                    continue

                try:
                    version = winreg.QueryValueEx(sk, "DisplayVersion")[0]
                except Exception:
                    pass

                try:
                    publisher = winreg.QueryValueEx(sk, "Publisher")[0]
                except Exception:
                    pass

                try:
                    install_date = winreg.QueryValueEx(sk, "InstallDate")[0]
                except Exception:
                    pass

                programs.append({
                    "name": name,
                    "version": version,
                    "publisher": publisher,
                    "install_date": install_date
                })
            except Exception:
                continue

    # Remoção simplificada de duplicados por (nome, versão)
    unique = {}
    for p in programs:
        key = (p["name"], p.get("version"))
        if key not in unique:
            unique[key] = p
    return list(unique.values())


# ---------------------------
# LIXEIRA ($Recycle.Bin)
# ---------------------------

def parse_i_file(i_path):
    """
    Parser simples de arquivos $I (Windows 7+).
    Formato:
      0x00: 8 bytes - versão
      0x08: 8 bytes - tamanho original (Q)
      0x10: 8 bytes - FILETIME da exclusão (Q)
      0x18: caminho original (UTF-16LE, null-terminated)
    """
    try:
        with open(i_path, "rb") as f:
            header = f.read(8)
            if len(header) < 8:
                return None

            size_bytes = f.read(8)
            time_bytes = f.read(8)
            if len(size_bytes) < 8 or len(time_bytes) < 8:
                return None

            orig_size = struct.unpack("<Q", size_bytes)[0]
            filetime_raw = struct.unpack("<Q", time_bytes)[0]
            deleted_dt = filetime_to_dt(filetime_raw)

            rest = f.read()
            try:
                orig_path = rest.decode("utf-16le", errors="ignore").rstrip("\x00")
            except Exception:
                orig_path = "(caminho original indisponível)"

            return {
                "original_path": orig_path,
                "original_size": orig_size,
                "deleted_time": deleted_dt
            }
    except Exception:
        return None


def get_recycle_bin_entries():
    """
    Varre unidades em busca da pasta $Recycle.Bin e tenta
    reconstruir itens da lixeira via arquivos $I*.
    """
    entries = []

    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        recycle_root = os.path.join(root, "$Recycle.Bin")
        if not os.path.isdir(recycle_root):
            continue

        for sid_dir in os.listdir(recycle_root):
            sid_path = os.path.join(recycle_root, sid_dir)
            if not os.path.isdir(sid_path):
                continue

            for fname in os.listdir(sid_path):
                if not fname.startswith("$I"):
                    continue
                i_path = os.path.join(sid_path, fname)
                info = parse_i_file(i_path)
                if not info:
                    continue

                suffix = fname[2:]  # remove "$I"
                r_name = f"$R{suffix}"
                r_path = os.path.join(sid_path, r_name)
                exists = os.path.exists(r_path)

                entries.append({
                    "original_path": info["original_path"],
                    "original_size": info["original_size"],
                    "deleted_time": info["deleted_time"],
                    "recycle_path": r_path if exists else "(conteúdo não encontrado)",
                    "drive": letter
                })

    return entries


# ---------------------------
# TIMELINE: EVENTOS
# ---------------------------

def add_system_event(events, system_info):
    """
    Adiciona um evento inicial de sistema à timeline.
    """
    dt = datetime.now(timezone.utc)
    events.append({
        "timestamp": dt,
        "category": "system",
        "source": "Coleta",
        "title": "Início da coleta forense",
        "details": (
            f"Host: {system_info.get('hostname')}<br>"
            f"Usuário: {system_info.get('user')}<br>"
            f"OS: {system_info.get('os')} {system_info.get('release')}<br>"
            f"IP: {system_info.get('ip')}"
        )
    })


def add_recycle_events(events, recycle_entries):
    """
    Adiciona eventos da Lixeira à timeline.
    """
    for e in recycle_entries:
        dt = e.get("deleted_time")
        if dt is None:
            continue
        events.append({
            "timestamp": dt,
            "category": "recycle",
            "source": f"Lixeira {e.get('drive')}:",
            "title": "Arquivo excluído",
            "details": (
                f"Caminho original: {e.get('original_path')}<br>"
                f"Tamanho (bytes): {e.get('original_size')}<br>"
                f"Local na lixeira: {e.get('recycle_path')}"
            )
        })


# ---------------------------
# HARDWARE VIA WMIC
# ---------------------------

def run_wmic(command_list):
    """
    Executa um comando WMIC e retorna a saída como texto.
    Exemplo: ['csproduct', 'get', 'name,vendor,identifyingnumber']
    """
    try:
        full_cmd = ["wmic"] + command_list
        out = subprocess.check_output(
            full_cmd,
            text=True,
            stderr=subprocess.DEVNULL
        )
        return out.strip()
    except Exception:
        return "Não disponível ou WMIC ausente nesta versão do Windows."


def get_hardware_raw():
    """
    Coleta algumas informações de hardware / sistema via WMIC,
    armazenando a saída bruta para exibir em <pre> no HTML.
    """
    hw = {}
    hw["csproduct"] = run_wmic(["csproduct", "get", "name,vendor,identifyingnumber"])
    hw["cpu"] = run_wmic(["cpu", "get", "name,numberofcores,numberoflogicalprocessors"])
    hw["os"] = run_wmic(["os", "get", "Caption,Version,SerialNumber,CSName"])
    hw["memory"] = run_wmic(["path", "win32_physicalmemory", "get", "capacity,speed,manufacturer"])
    hw["diskdrive"] = run_wmic(["diskdrive", "get", "model,size,serialnumber,interfacetype"])
    return hw


# ---------------------------
# DISCOS LÓGICOS
# ---------------------------

def get_disks_info():
    """
    Lista discos lógicos (C:, D:, etc.) com tamanho total, usado e livre.
    """
    disks = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        try:
            total, used, free = shutil.disk_usage(root)
            disks.append({
                "letter": letter,
                "total": total,
                "used": used,
                "free": free
            })
        except Exception:
            continue
    return disks


# ---------------------------
# HISTÓRICO DE DISPOSITIVOS USB (USBSTOR)
# ---------------------------

def get_usb_storage_history():
    """
    Enumera dispositivos de armazenamento USB conhecidos a partir do Registro:
    HKLM\\SYSTEM\\CurrentControlSet\\Enum\\USBSTOR

    Não traz datas, mas ajuda a identificar pendrives / HDs externos
    que já foram conectados.
    """
    devices = []
    if winreg is None:
        return devices

    base_path = r"SYSTEM\CurrentControlSet\Enum\USBSTOR"
    try:
        base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path)
    except Exception:
        return devices

    i = 0
    while True:
        try:
            dev_name = winreg.EnumKey(base_key, i)
            i += 1
        except OSError:
            break

        dev_path = base_path + "\\" + dev_name
        try:
            dev_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, dev_path)
        except Exception:
            continue

        j = 0
        while True:
            try:
                inst_name = winreg.EnumKey(dev_key, j)
                j += 1
            except OSError:
                break

            inst_path = dev_path + "\\" + inst_name
            try:
                inst_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, inst_path)
            except Exception:
                continue

            friendly = None
            try:
                friendly = winreg.QueryValueEx(inst_key, "FriendlyName")[0]
            except Exception:
                pass

            service = None
            try:
                service = winreg.QueryValueEx(inst_key, "Service")[0]
            except Exception:
                pass

            # Serial aproximado a partir do nome da instância
            serial_guess = inst_name.split("&")[0].split("#")[0]

            devices.append({
                "device_key": dev_name,
                "instance": inst_name,
                "friendly_name": friendly,
                "service": service,
                "serial_guess": serial_guess
            })

    return devices


# ---------------------------
# RELATÓRIO HTML COM ABAS
# ---------------------------

def generate_html_report(output_path, system_info, events, installed_programs,
                         recycle_entries, hardware_raw, disks_info, usb_devices):
    """
    Gera o relatório HTML completo, com abas e timeline.
    """
    # Ordena eventos por data/hora
    events_sorted = sorted(
        [e for e in events if e.get("timestamp") is not None],
        key=lambda x: x["timestamp"]
    )

    def esc(s):
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html = []
    html.append("<!DOCTYPE html>")
    html.append("<html lang='pt-BR'>")
    html.append("<head>")
    html.append("<meta charset='UTF-8'>")
    html.append("<title>Relatório Forense Windows</title>")
    html.append("<style>")
    html.append("""
    body {
        font-family: Arial, Helvetica, sans-serif;
        background: #f5f7fa;
        color: #222;
        margin: 0;
        padding: 0;
    }
    header {
        background: linear-gradient(135deg, #4A8BDF, #A0006D);
        color: #fff;
        padding: 20px 30px;
    }
    header h1 {
        margin: 0;
        font-size: 24px;
    }
    header p {
        margin: 5px 0 0;
        font-size: 13px;
        opacity: 0.9;
    }
    .container {
        padding: 20px 30px 40px;
        max-width: 1200px;
        margin: 0 auto;
    }
    .card {
        background: #fff;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.06);
        margin-bottom: 20px;
        padding: 16px 20px;
    }
    .card h2 {
        margin-top: 0;
        font-size: 18px;
        border-bottom: 1px solid #eee;
        padding-bottom: 8px;
    }
    .grid-2 {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 16px;
    }
    .meta-list dt {
        font-weight: bold;
    }
    .meta-list dd {
        margin: 0 0 6px 0;
    }
    .badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: bold;
        color: #fff;
        margin-right: 4px;
    }
    .badge-browser { background: #4A8BDF; }
    .badge-system  { background: #444; }
    .badge-recycle { background: #A0006D; }
    .badge-other   { background: #888; }

    /* TABS */
    .tab-bar {
        display: flex;
        flex-wrap: wrap;
        border-bottom: 1px solid #d0d9e8;
        margin-bottom: 10px;
        gap: 4px;
    }
    .tab-link {
        border: none;
        background: #e5ecf6;
        color: #2b3b52;
        padding: 8px 14px;
        border-radius: 999px 999px 0 0;
        cursor: pointer;
        font-size: 13px;
    }
    .tab-link.active {
        background: #fff;
        border-bottom: 2px solid #fff;
        box-shadow: 0 -2px 4px rgba(0,0,0,0.06);
    }
    .tab-content {
        display: none;
    }
    .tab-content.active {
        display: block;
    }

    /* TIMELINE */
    .timeline {
        position: relative;
        margin: 0;
        padding: 0 0 0 20px;
        list-style: none;
    }
    .timeline::before {
        content: "";
        position: absolute;
        left: 7px;
        top: 0;
        bottom: 0;
        width: 2px;
        background: #d0d9e8;
    }
    .event {
        position: relative;
        margin-bottom: 14px;
        padding-left: 18px;
    }
    .event::before {
        content: "";
        position: absolute;
        left: -1px;
        top: 4px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #ccc;
        box-shadow: 0 0 0 3px #f5f7fa;
    }
    .event.browser::before { background: #4A8BDF; }
    .event.system::before  { background: #444; }
    .event.recycle::before { background: #A0006D; }
    .event-time {
        font-size: 11px;
        color: #65748b;
    }
    .event-title {
        font-size: 14px;
        font-weight: bold;
        margin: 2px 0 2px;
    }
    .event-meta {
        font-size: 11px;
        color: #888;
    }
    .event-details {
        font-size: 12px;
        margin-top: 3px;
    }

    .table-small {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
    }
    .table-small th, .table-small td {
        border-bottom: 1px solid #eee;
        padding: 4px 6px;
        text-align: left;
    }
    .table-small th {
        background: #f0f3f9;
        font-weight: bold;
    }

    #filterBar {
        margin-bottom: 10px;
        font-size: 12px;
    }
    #filterBar label {
        margin-right: 10px;
    }

    pre {
        background: #f0f3f9;
        padding: 8px 10px;
        border-radius: 6px;
        overflow-x: auto;
        font-size: 11px;
    }
    """)
    html.append("</style>")
    html.append("</head>")
    html.append("<body>")

    # Header
    html.append("<header>")
    html.append("<h1>Relatório Forense Windows</h1>")
    html.append(f"<p>Gerado em {esc(system_info.get('now'))} | Host: {esc(system_info.get('hostname'))} | Usuário: {esc(system_info.get('user'))}</p>")
    html.append("</header>")

    html.append("<div class='container'>")

    # Barra de abas
    html.append("<div class='tab-bar'>")
    html.append("<button class='tab-link active' onclick=\"openTab('tab-overview', this)\">Visão Geral</button>")
    html.append("<button class='tab-link' onclick=\"openTab('tab-timeline', this)\">Timeline</button>")
    html.append("<button class='tab-link' onclick=\"openTab('tab-programs', this)\">Programas Instalados</button>")
    html.append("<button class='tab-link' onclick=\"openTab('tab-recycle', this)\">Lixeira</button>")
    html.append("<button class='tab-link' onclick=\"openTab('tab-hardware', this)\">Hardware & Discos</button>")
    html.append("<button class='tab-link' onclick=\"openTab('tab-usb', this)\">USB & Dispositivos</button>")
    html.append("</div>")

    # ------------------- ABA: VISÃO GERAL -------------------
    html.append("<div id='tab-overview' class='tab-content active'>")
    html.append("<div class='card'>")
    html.append("<h2>Visão Geral do Sistema</h2>")
    html.append("<div class='grid-2'>")

    html.append("<div>")
    html.append("<dl class='meta-list'>")
    html.append(f"<dt>Host</dt><dd>{esc(system_info.get('hostname'))}</dd>")
    html.append(f"<dt>Usuário</dt><dd>{esc(system_info.get('user'))}</dd>")
    html.append(f"<dt>OS</dt><dd>{esc(system_info.get('os'))} {esc(system_info.get('release'))}</dd>")
    html.append(f"<dt>Versão</dt><dd>{esc(system_info.get('os_version'))}</dd>")
    html.append(f"<dt>IP</dt><dd>{esc(system_info.get('ip'))}</dd>")
    html.append("</dl>")
    html.append("</div>")

    browser_count = sum(1 for e in events_sorted if e["category"] == "browser")
    recycle_count = len(recycle_entries)
    apps_count = len(installed_programs)
    total_events = len(events_sorted)

    html.append("<div>")
    html.append("<dl class='meta-list'>")
    html.append(f"<dt>Eventos na timeline</dt><dd>{total_events}</dd>")
    html.append(f"<dt>Entradas de histórico de navegação</dt><dd>{browser_count}</dd>")
    html.append(f"<dt>Arquivos na Lixeira</dt><dd>{recycle_count}</dd>")
    html.append(f"<dt>Programas instalados</dt><dd>{apps_count}</dd>")
    html.append("</dl>")
    html.append("</div>")

    html.append("</div>")
    html.append("</div>")
    html.append("</div>")  # tab-overview

    # ------------------- ABA: TIMELINE -------------------
    html.append("<div id='tab-timeline' class='tab-content'>")
    html.append("<div class='card'>")
    html.append("<h2>Timeline Consolidada</h2>")

    html.append("""
    <div id="filterBar">
      <label><input type="checkbox" checked onclick="toggleCategory('browser', this)"> Navegação</label>
      <label><input type="checkbox" checked onclick="toggleCategory('system', this)"> Sistema</label>
      <label><input type="checkbox" checked onclick="toggleCategory('recycle', this)"> Lixeira</label>
    </div>
    """)

    html.append("<ul class='timeline' id='timeline'>")
    for e in events_sorted:
        cat = e.get("category", "other")
        source = e.get("source", "")
        ts = e["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        title = esc(e.get("title"))
        details = e.get("details") or ""
        badge_cat = cat if cat in ["browser", "system", "recycle"] else "other"
        html.append(f"<li class='event {cat}'>")
        html.append(f"<div class='event-time'>{ts}</div>")
        html.append(f"<div class='event-title'>{title}</div>")
        html.append(f"<div class='event-meta'>{esc(source)} | <span class='badge badge-{badge_cat}'>{cat}</span></div>")
        html.append(f"<div class='event-details'>{details}</div>")
        html.append("</li>")
    html.append("</ul>")
    html.append("</div>")
    html.append("</div>")  # tab-timeline

    # ------------------- ABA: PROGRAMAS INSTALADOS -------------------
    html.append("<div id='tab-programs' class='tab-content'>")
    html.append("<div class='card'>")
    html.append("<h2>Programas Instalados</h2>")
    html.append("<div style='max-height:400px; overflow:auto;'>")
    html.append("<table class='table-small'>")
    html.append("<tr><th>Nome</th><th>Versão</th><th>Publicador</th><th>Data Instalação</th></tr>")
    for p in sorted(installed_programs, key=lambda x: x.get("name", "").lower()):
        html.append("<tr>")
        html.append(f"<td>{esc(p.get('name'))}</td>")
        html.append(f"<td>{esc(p.get('version'))}</td>")
        html.append(f"<td>{esc(p.get('publisher'))}</td>")
        html.append(f"<td>{esc(p.get('install_date'))}</td>")
        html.append("</tr>")
    html.append("</table>")
    html.append("</div>")
    html.append("</div>")
    html.append("</div>")  # tab-programs

    # ------------------- ABA: LIXEIRA -------------------
    html.append("<div id='tab-recycle' class='tab-content'>")
    html.append("<div class='card'>")
    html.append("<h2>Arquivos na Lixeira (Reconstruídos)</h2>")
    html.append("<div style='max-height:400px; overflow:auto;'>")
    html.append("<table class='table-small'>")
    html.append("<tr><th>Data Exclusão</th><th>Arquivo original</th><th>Tamanho (bytes)</th><th>Unidade</th><th>Caminho na lixeira</th></tr>")
    for e in sorted(
        [x for x in recycle_entries if x.get("deleted_time")],
        key=lambda x: x["deleted_time"],
        reverse=True
    ):
        dt = e["deleted_time"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        html.append("<tr>")
        html.append(f"<td>{esc(dt)}</td>")
        html.append(f"<td>{esc(e.get('original_path'))}</td>")
        html.append(f"<td>{esc(e.get('original_size'))}</td>")
        html.append(f"<td>{esc(e.get('drive'))}:</td>")
        html.append(f"<td>{esc(e.get('recycle_path'))}</td>")
        html.append("</tr>")
    html.append("</table>")
    html.append("</div>")
    html.append("</div>")
    html.append("</div>")  # tab-recycle

    # ------------------- ABA: HARDWARE & DISCOS -------------------
    html.append("<div id='tab-hardware' class='tab-content'>")
    html.append("<div class='card'>")
    html.append("<h2>Hardware (WMIC bruto)</h2>")

    for key, label in [
        ("csproduct", "Computador / Fabricante / UUID"),
        ("cpu", "Processador"),
        ("memory", "Memória RAM – módulos físicos"),
        ("diskdrive", "Discos físicos (modelo / interface / tamanho)"),
        ("os", "Sistema Operacional / SerialNumber")
    ]:
        html.append(f"<h3 style='font-size:14px; margin-top:16px;'>{esc(label)}</h3>")
        html.append("<pre>")
        html.append(esc(hardware_raw.get(key, "")))
        html.append("</pre>")

    html.append("</div>")  # card hardware

    html.append("<div class='card'>")
    html.append("<h2>Discos Lógicos (C:, D:, ...)</h2>")
    html.append("<div style='max-height:400px; overflow:auto;'>")
    html.append("<table class='table-small'>")
    html.append("<tr><th>Unidade</th><th>Tamanho Total (GB)</th><th>Usado (GB)</th><th>Livre (GB)</th></tr>")
    for d in disks_info:
        total_gb = d["total"] / (1024**3)
        used_gb = d["used"] / (1024**3)
        free_gb = d["free"] / (1024**3)
        html.append("<tr>")
        html.append(f"<td>{esc(d['letter'])}:</td>")
        html.append(f"<td>{total_gb:.2f}</td>")
        html.append(f"<td>{used_gb:.2f}</td>")
        html.append(f"<td>{free_gb:.2f}</td>")
        html.append("</tr>")
    html.append("</table>")
    html.append("</div>")
    html.append("</div>")  # card discos

    html.append("</div>")  # tab-hardware

    # ------------------- ABA: USB & DISPOSITIVOS -------------------
    html.append("<div id='tab-usb' class='tab-content'>")
    html.append("<div class='card'>")
    html.append("<h2>Histórico de Dispositivos USB de Armazenamento (USBSTOR)</h2>")
    html.append("<p style='font-size:12px; color:#555;'>Origem: Registro em HKLM\\SYSTEM\\CurrentControlSet\\Enum\\USBSTOR.</p>")
    html.append("<div style='max-height:400px; overflow:auto;'>")
    html.append("<table class='table-small'>")
    html.append("<tr><th>Device Key</th><th>Instância</th><th>Nome Amigável</th><th>Serviço</th><th>Serial (estimado)</th></tr>")
    for dev in usb_devices:
        html.append("<tr>")
        html.append(f"<td>{esc(dev.get('device_key'))}</td>")
        html.append(f"<td>{esc(dev.get('instance'))}</td>")
        html.append(f"<td>{esc(dev.get('friendly_name'))}</td>")
        html.append(f"<td>{esc(dev.get('service'))}</td>")
        html.append(f"<td>{esc(dev.get('serial_guess'))}</td>")
        html.append("</tr>")
    html.append("</table>")
    html.append("</div>")
    html.append("</div>")
    html.append("</div>")  # tab-usb

    # ------------------- JS PARA ABAS E FILTRO DA TIMELINE -------------------
    html.append("""
    <script>
    function openTab(id, btn) {
        var tabs = document.querySelectorAll('.tab-content');
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.remove('active');
        }
        var buttons = document.querySelectorAll('.tab-link');
        for (var j = 0; j < buttons.length; j++) {
            buttons[j].classList.remove('active');
        }
        document.getElementById(id).classList.add('active');
        btn.classList.add('active');
    }

    function toggleCategory(cat, checkbox) {
        var items = document.querySelectorAll('.event.' + cat);
        for (var i = 0; i < items.length; i++) {
            items[i].style.display = checkbox.checked ? '' : 'none';
        }
    }
    </script>
    """)

    html.append("</div>")  # container
    html.append("</body></html>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html))


# ---------------------------
# MAIN
# ---------------------------

def main():
    system_info = get_system_info()
    events = []

    # Evento inicial de sistema na timeline
    add_system_event(events, system_info)

    # Históricos de navegação
    collect_browser_histories(events)

    # Lixeira
    recycle_entries = get_recycle_bin_entries()
    add_recycle_events(events, recycle_entries)

    # Programas instalados
    installed_programs = get_installed_programs()

    # Hardware bruto via WMIC
    hardware_raw = get_hardware_raw()

    # Discos lógicos
    disks_info = get_disks_info()

    # Histórico de dispositivos USB
    usb_devices = get_usb_storage_history()

    # Saída
    output_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
    output_path = os.path.join(output_dir, "relatorio_forense_windows.html")

    generate_html_report(
        output_path=output_path,
        system_info=system_info,
        events=events,
        installed_programs=installed_programs,
        recycle_entries=recycle_entries,
        hardware_raw=hardware_raw,
        disks_info=disks_info,
        usb_devices=usb_devices
    )

    print("Relatório gerado em:")
    print(output_path)
    input("\nPressione ENTER para sair...")


if __name__ == "__main__":
    main()
