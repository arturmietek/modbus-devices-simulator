# modbus-devices-simulator

GUI simulator Modbus TCP z obsługą wielu slave'ów jednocześnie. Umożliwia edycję rejestrów (Holding, Input, Coils, Discrete Inputs) w czasie rzeczywistym oraz zapis/odczyt konfiguracji do pliku JSON.

## Wymagania

- Python 3.13+
- PySide6
- pyModbusTCP

## Pierwsze uruchomienie

```bash
cd ~/projects/modbus/modbus-devices-simulator

# Utwórz wirtualne środowisko
python3 -m venv .venv

# Aktywuj
source .venv/bin/activate

# Zainstaluj zależności
pip install -r requirements.txt
```

## Uruchamianie

```bash
cd ~/projects/modbus/modbus-devices-simulator
source .venv/bin/activate

# Domyślna konfiguracja (config.json w katalogu skryptu)
python modbus_gui.py

# Alternatywna konfiguracja (preset z katalogu devices)
python modbus_gui.py --config ../devices/diy-driveway-controller/simulator-preset.json

# Tryb debugowania — każde zapytanie Modbus logowane na terminal
python modbus_gui.py --debug
python modbus_gui.py --config ../devices/diy-driveway-controller/simulator-preset.json --debug
```

Przy starcie w terminalu pojawi się informacja, który plik konfiguracji jest używany:
```
[config] Plik konfiguracji: /path/to/config.json
[config] Wczytano: /path/to/config.json
```

Przykładowy output w trybie `--debug`:
```
[modbus] read_input_registers    slave=1 addr=0 count=4 -> [0, 500, 12000, 0]
[modbus] read_coils              slave=1 addr=0 count=1 -> [False]
[modbus] write_coils             slave=1 addr=0 values=[True]
```

## Funkcje

- Dodawanie i usuwanie slave'ów (ID 0–247)
- Edycja Holding Registers, Input Registers, Coils, Discrete Inputs
- Serwer TCP na dowolnym hoście i porcie (domyślnie `0.0.0.0:5020`)
- Automatyczna synchronizacja GUI ↔ serwer co 200/500ms
- Zapis i wczytywanie konfiguracji z pliku JSON
- Przy zamknięciu pytanie: zapisz / porzuć zmiany / anuluj — bezpieczne dla presetów
- Obsługa wielu presetów przez `--config`
- Tryb `--debug` logujący każde zapytanie Modbus na terminal

## Testowanie z pymodbus REPL

```bash
pymodbus.console tcp --host 127.0.0.1 --port 5020
```

Podstawowe komendy:
```
client.read_holding_registers address=0 count=10 slave=1
client.write_register address=0 value=123 slave=1
client.read_coils address=0 count=8 slave=1
client.write_coil address=0 value=True slave=1
```

> Instalacja pymodbus REPL — patrz `../pymodbus-repl.md`
