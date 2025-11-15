# WinForense

WinForense é uma ferramenta simples de **análise forense em Windows**, escrita em Python, focada em coleta rápida de artefatos locais e geração de um **relatório HTML organizado em abas**.

O objetivo é facilitar uma visão geral do ambiente analisado (máquina viva), sem depender de suites forenses pesadas, servindo como apoio didático e como checklist inicial de evidências.

---

## Funcionalidades

Atualmente o WinForense coleta e organiza:

- **Informações de sistema**
  - Hostname, usuário logado, versão do Windows, IP interno
- **Histórico de navegação**
  - Principais navegadores baseados em Chromium:
    - Chrome, Edge, Brave, Opera
  - Firefox (primeiro perfil encontrado)
  - URLs visitadas, título da página, contagem de visitas
- **Programas instalados**
  - Leitura do Registro em:
    - `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`
    - `HKLM\SOFTWARE\WOW6432Node\...\Uninstall`
    - `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`
- **Lixeira (`$Recycle.Bin`)**
  - Reconstrução de arquivos excluídos via arquivos `$I*` / `$R*`
  - Caminho original, tamanho, data/hora de exclusão
- **Hardware via WMIC (saída bruta)**
  - `csproduct` (fabricante, modelo, identifying number)
  - `cpu` (nome, núcleos físicos e lógicos)
  - `os` (Caption, Version, SerialNumber, CSName)
  - `win32_physicalmemory` (capacity, speed, manufacturer)
  - `diskdrive` (modelo, tamanho, serial, interface)
- **Discos lógicos**
  - Unidades `C:, D:, ...` com tamanho total, usado e livre (em GB)
- **Histórico de dispositivos USB de armazenamento**
  - Leitura da chave:
    - `HKLM\SYSTEM\CurrentControlSet\Enum\USBSTOR`
  - Device key, instância, nome amigável (quando presente), serviço e “serial” estimado

Tudo isso é consolidado em um **relatório HTML** com abas:

- Visão Geral  
- Timeline  
- Programas Instalados  
- Lixeira  
- Hardware & Discos  
- USB & Dispositivos  

---

## Requisitos

- Windows 10/11 (execução como usuário com permissão de leitura ao Registro e sistema de arquivos)
- Python 3.10+ (testado com Python 3.14)
- Módulos padrão da biblioteca do Python

### Bibliotecas opcionais

- `pyinstaller` – para gerar `.exe` standalone
- `requests` – se você ativar a coleta de **IP externo** (ver seção de melhorias no código)

Instalação opcional de libs:

```bash
py -m pip install pyinstaller requests
