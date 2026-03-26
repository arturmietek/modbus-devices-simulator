#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modbus Multi-Slave GUI Simulator
- pyModbusTCP server with MultiSlaveHandler
- PySide6 GUI: add/remove slaves, edit Holding/Input/Coils
- Autorefresh both directions (GUI -> server, server -> GUI)
- Save/load JSON config
Author: ChatGPT (adapted for user's request)
"""

import sys
import os
import json
import threading
import traceback
import argparse
from dataclasses import dataclass, asdict
from typing import Dict, Any, List

from PySide6 import QtCore, QtWidgets, QtGui

# pyModbusTCP imports
try:
    from pyModbusTCP.server import ModbusServer, DataHandler
    from pyModbusTCP.constants import EXP_NONE
except Exception as e:
    raise RuntimeError("Brak biblioteki pyModbusTCP lub nie można zaimportować wymaganych klas. "
                       "Zainstaluj pyModbusTCP: pip install pyModbusTCP\nOrig error: " + str(e))


SYNC_TO_SERVER_MS = 200
REFRESH_FROM_SERVER_MS = 500


@dataclass
class HoldingRegister:
    addr: int
    value: int


@dataclass
class InputRegister:
    addr: int
    value: int


@dataclass
class Coil:
    addr: int
    value: bool

@dataclass
class DescreteInput:
    addr: int
    value: bool


@dataclass
class SlaveConfig:
    slave_id: int
    holding: List[HoldingRegister]
    input_regs: List[InputRegister]
    coils: List[Coil]
    descrete_inputs: List[DescreteInput]


class MultiSlaveHandler(DataHandler):
    """
    DataHandler-compatible object storing separate address spaces per slave_id.
    Methods follow the DataHandler interface used by pyModbusTCP server.
    """

    def __init__(self, debug: bool = False):
        super().__init__()
        # For each slave_id keep dicts: holding registers, analog inputs, coils, descrete inputs
        # values stored as {addr: value}
        self.lock = threading.RLock()
        self.slaves: Dict[int, Dict[str, Dict[int, Any]]] = {}
        self.debug = debug

    def _log(self, msg: str):
        if self.debug:
            print(f"[modbus] {msg}")

    def ensure_slave(self, slave_id: int):
        with self.lock:
            if slave_id not in self.slaves:
                self.slaves[slave_id] = {
                    "holding": {},
                    "input": {},
                    "coils": {},
                    "descrete_inputs": {}
                }

    # ---------- Holding Registers ----------
    def read_h_regs(self, address, count, srv_info=None):
        sid = srv_info.recv_frame.mbap.unit_id
        self.ensure_slave(sid)
        with self.lock:
            base = self.slaves[sid]["holding"]
            result = [int(base.get(address + i, 0)) & 0xFFFF for i in range(count)]
        self._log(f"read_holding_registers  slave={sid} addr={address} count={count} -> {result}")
        return DataHandler.Return(exp_code=EXP_NONE, data=result)

    def write_h_regs(self, address, word_list, srv_info=None):
        sid = srv_info.recv_frame.mbap.unit_id
        self.ensure_slave(sid)
        with self.lock:
            base = self.slaves[sid]["holding"]
            for i, v in enumerate(word_list):
                base[address + i] = int(v) & 0xFFFF
        self._log(f"write_holding_registers slave={sid} addr={address} values={list(word_list)}")
        return DataHandler.Return(exp_code=EXP_NONE)

    # ---------- Input Registers ----------
    def read_i_regs(self, address, count, srv_info=None):
        sid = srv_info.recv_frame.mbap.unit_id
        self.ensure_slave(sid)
        with self.lock:
            base = self.slaves[sid]["input"]
            result = [int(base.get(address + i, 0)) & 0xFFFF for i in range(count)]
        self._log(f"read_input_registers    slave={sid} addr={address} count={count} -> {result}")
        return DataHandler.Return(exp_code=EXP_NONE, data=result)

    # ---------- Coils (bits) ----------
    def read_coils(self, address, count, srv_info=None):
        sid = srv_info.recv_frame.mbap.unit_id
        self.ensure_slave(sid)
        with self.lock:
            base = self.slaves[sid]["coils"]
            result = [bool(base.get(address + i, False)) for i in range(count)]
        self._log(f"read_coils              slave={sid} addr={address} count={count} -> {result}")
        return DataHandler.Return(exp_code=EXP_NONE, data=result)

    def write_coils(self, address, bit_list, srv_info=None):
        sid = srv_info.recv_frame.mbap.unit_id
        self.ensure_slave(sid)
        with self.lock:
            base = self.slaves[sid]["coils"]
            for i, b in enumerate(bit_list):
                base[address + i] = bool(b)
        self._log(f"write_coils             slave={sid} addr={address} values={list(bit_list)}")
        return DataHandler.Return(exp_code=EXP_NONE)

    def read_d_inputs(self, address, count, srv_info):
        sid = srv_info.recv_frame.mbap.unit_id
        self.ensure_slave(sid)
        with self.lock:
            base = self.slaves[sid]["descrete_inputs"]
            result = [bool(base.get(address + i, False)) for i in range(count)]
        self._log(f"read_discrete_inputs    slave={sid} addr={address} count={count} -> {result}")
        return DataHandler.Return(exp_code=EXP_NONE, data=result)


    # Utility for GUI/serialization
    def set_holding(self, slave_id: int, addr: int, value: int):
        self.ensure_slave(slave_id)
        with self.lock:
            self.slaves[slave_id]["holding"][addr] = int(value) & 0xFFFF

    def set_input(self, slave_id: int, addr: int, value: int):
        self.ensure_slave(slave_id)
        with self.lock:
            self.slaves[slave_id]["input"][addr] = int(value) & 0xFFFF

    def set_coil(self, slave_id: int, addr: int, value: bool):
        self.ensure_slave(slave_id)
        with self.lock:
            self.slaves[slave_id]["coils"][addr] = bool(value)

    def get_holding_list(self, slave_id: int):
        self.ensure_slave(slave_id)
        with self.lock:
            return dict(self.slaves[slave_id]["holding"])

    def get_input_list(self, slave_id: int):
        self.ensure_slave(slave_id)
        with self.lock:
            return dict(self.slaves[slave_id]["input"])

    def get_coils_list(self, slave_id: int):
        self.ensure_slave(slave_id)
        with self.lock:
            return dict(self.slaves[slave_id]["coils"])

    def export_all(self):
        """Return complete structure for saving to JSON"""
        with self.lock:
            out = {}
            for sid, blocks in self.slaves.items():
                out[sid] = {
                    "holding": [{ "addr": a, "value": v } for a, v in sorted(blocks["holding"].items())],
                    "input":   [{ "addr": a, "value": v } for a, v in sorted(blocks["input"].items())],
                    "coils":   [{ "addr": a, "value": bool(v) } for a, v in sorted(blocks["coils"].items())],
                    "descrete_inputs":   [{ "addr": a, "value": bool(v) } for a, v in sorted(blocks["descrete_inputs"].items())],
                }
            return out

    def import_all(self, data: Dict[int, Dict[str, List[Dict[str, Any]]]]):
        with self.lock:
            self.slaves = {}
            for sid, blocks in data.items():
                sid_i = int(sid)
                self.slaves[sid_i] = {"holding": {}, "input": {}, "coils": {}, "descrete_inputs": {}}
                for r in blocks.get("holding", []):
                    self.slaves[sid_i]["holding"][int(r["addr"])] = int(r["value"]) & 0xFFFF
                for r in blocks.get("input", []):
                    self.slaves[sid_i]["input"][int(r["addr"])] = int(r["value"]) & 0xFFFF
                for r in blocks.get("coils", []):
                    self.slaves[sid_i]["coils"][int(r["addr"])] = bool(r["value"])
                for r in blocks.get("descrete_inputs", []):
                    self.slaves[sid_i]["descrete_inputs"][int(r["addr"])] = bool(r["value"])


# ----------------- GUI -----------------
class RegistersTable(QtWidgets.QWidget):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, len(columns), self)
        self.table.setHorizontalHeaderLabels(columns)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.table)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("Dodaj")
        self.btn_remove = QtWidgets.QPushButton("Usuń zaznaczone")
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        self.layout.addLayout(btn_layout)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, config_path: str, debug: bool = False):
        super().__init__()
        self.config_path = config_path
        self.setWindowTitle("Modbus Devices Simulator")


        self.resize(1000, 640)

        # Model / Server handler
        self.handler = MultiSlaveHandler(debug=debug)

        # Server instance (created on Start)
        self.server: ModbusServer | None = None
        self.server_running = False

        # UI
        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(central)
        self.setCentralWidget(central)

        # Left: slave list and controls
        left_col = QtWidgets.QVBoxLayout()
        main_layout.addLayout(left_col, 2)

        left_col.addWidget(QtWidgets.QLabel("Slave'y (ID):"))
        self.slave_list = QtWidgets.QListWidget()
        left_col.addWidget(self.slave_list, 1)

        sl_ctrls = QtWidgets.QHBoxLayout()
        self.input_new_slave = QtWidgets.QSpinBox()
        self.input_new_slave.setRange(0, 247)
        self.input_new_slave.setValue(1)
        self.btn_add_slave = QtWidgets.QPushButton("Dodaj slave")
        self.btn_remove_slave = QtWidgets.QPushButton("Usuń wybrany")
        sl_ctrls.addWidget(self.input_new_slave)
        sl_ctrls.addWidget(self.btn_add_slave)
        sl_ctrls.addWidget(self.btn_remove_slave)
        left_col.addLayout(sl_ctrls)

        left_col.addSpacing(10)
        left_col.addWidget(QtWidgets.QLabel("Konfiguracja serwera:"))
        srv_layout = QtWidgets.QHBoxLayout()
        srv_layout.addWidget(QtWidgets.QLabel("Host:"))
        self.input_host = QtWidgets.QLineEdit("0.0.0.0")
        self.input_host.setFixedWidth(140)
        srv_layout.addWidget(self.input_host)
        srv_layout.addWidget(QtWidgets.QLabel("Port:"))
        self.input_port = QtWidgets.QSpinBox()
        self.input_port.setRange(1, 65535)
        self.input_port.setValue(5020)
        self.input_port.setFixedWidth(100)
        srv_layout.addWidget(self.input_port)
        left_col.addLayout(srv_layout)

        srv_btns = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start servera")
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        srv_btns.addWidget(self.btn_start)
        srv_btns.addWidget(self.btn_stop)
        left_col.addLayout(srv_btns)

        left_col.addSpacing(10)
        left_col.addWidget(QtWidgets.QLabel("Plik konfiguracji:"))
        cfg_btns = QtWidgets.QHBoxLayout()
        self.btn_save = QtWidgets.QPushButton("Zapisz")
        self.btn_load = QtWidgets.QPushButton("Wczytaj")
        cfg_btns.addWidget(self.btn_save)
        cfg_btns.addWidget(self.btn_load)
        left_col.addLayout(cfg_btns)

        left_col.addStretch()
        self.status_label = QtWidgets.QLabel("Serwer: zatrzymany")
        left_col.addWidget(self.status_label)

        # Right: details for selected slave (tabs)
        right_col = QtWidgets.QVBoxLayout()
        main_layout.addLayout(right_col, 5)

        self.current_slave_label = QtWidgets.QLabel("Wybrany slave: brak")
        right_col.addWidget(self.current_slave_label)

        self.tabs = QtWidgets.QTabWidget()
        self.holding_table = RegistersTable(["Adres", "Wartość (0..65535)"])
        self.input_table = RegistersTable(["Adres", "Wartość (0..65535)"])
        self.coils_table = RegistersTable(["Adres", "Wartość (True/False)"])
        self.descrete_inputs_table = RegistersTable(["Adres", "Wartość (True/False)"])
        self.tabs.addTab(self.holding_table, "Holding Registers")
        self.tabs.addTab(self.input_table, "Input Registers")
        self.tabs.addTab(self.coils_table, "Coils")
        self.tabs.addTab(self.descrete_inputs_table, "Descrete Inputs")
        right_col.addWidget(self.tabs, 1)

        # bottom controls for selected slave
        bottom_row = QtWidgets.QHBoxLayout()
        self.btn_push_now = QtWidgets.QPushButton("Wypchnij do serwera (teraz)")
        self.btn_pull_now = QtWidgets.QPushButton("Pobierz ze serwera (teraz)")
        bottom_row.addWidget(self.btn_push_now)
        bottom_row.addWidget(self.btn_pull_now)
        bottom_row.addStretch()
        right_col.addLayout(bottom_row)

        # Connections
        self.btn_add_slave.clicked.connect(self.on_add_slave)
        self.btn_remove_slave.clicked.connect(self.on_remove_slave)
        self.slave_list.currentItemChanged.connect(self.on_select_slave)

        self.holding_table.btn_add.clicked.connect(self.add_holding_row)
        self.holding_table.btn_remove.clicked.connect(lambda: self.remove_selected(self.holding_table))
        self.input_table.btn_add.clicked.connect(self.add_input_row)
        self.input_table.btn_remove.clicked.connect(lambda: self.remove_selected(self.input_table))
        self.coils_table.btn_add.clicked.connect(self.add_coil_row)
        self.coils_table.btn_remove.clicked.connect(lambda: self.remove_selected(self.coils_table))
        self.descrete_inputs_table.btn_add.clicked.connect(self.add_descrete_input_row)
        self.descrete_inputs_table.btn_remove.clicked.connect(lambda: self.remove_selected(self.descrete_inputs_table))
        self.coils_table.btn_remove.clicked.connect(lambda: self.remove_selected(self.coils_table))

        self.btn_start.clicked.connect(self.start_server)
        self.btn_stop.clicked.connect(self.stop_server)

        self.btn_save.clicked.connect(self.save_config)
        self.btn_load.clicked.connect(self.load_config)

        self.btn_push_now.clicked.connect(self.push_to_handler)
        self.btn_pull_now.clicked.connect(self.pull_from_handler)

        # Timers for background sync
        self.sync_timer = QtCore.QTimer(self)
        self.sync_timer.setInterval(SYNC_TO_SERVER_MS)
        self.sync_timer.timeout.connect(self.periodic_sync_to_handler)
        self.sync_timer.start()

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(REFRESH_FROM_SERVER_MS)
        self.refresh_timer.timeout.connect(self.periodic_refresh_from_handler)
        self.refresh_timer.start()

        # Load config if exists
        print(f"[config] Plik konfiguracji: {self.config_path}")
        if os.path.exists(self.config_path):
            try:
                self.load_config_from_path(self.config_path)
                print(f"[config] Wczytano: {self.config_path}")
                self.status("Wczytano konfigurację: " + self.config_path)
            except Exception:
                print(f"[config] Nie udało się wczytać: {self.config_path}")
                self.status("Nie udało się wczytać konfiguracji (użyto domyślnej).")
        else:
            print(f"[config] Brak pliku konfiguracji, zostanie utworzony przy zamknięciu")

    # ---------- Slave list management ----------
    def on_add_slave(self):
        sid = int(self.input_new_slave.value())
        # ensure unique
        for i in range(self.slave_list.count()):
            if int(self.slave_list.item(i).text()) == sid:
                QtWidgets.QMessageBox.warning(self, "Uwaga", f"Slave o ID {sid} już istnieje.")
                return
        self.slave_list.addItem(str(sid))
        self.handler.ensure_slave(sid)
        # select new
        self.slave_list.setCurrentRow(self.slave_list.count() - 1)

    def on_remove_slave(self):
        cur = self.slave_list.currentItem()
        if not cur:
            return
        sid = int(cur.text())
        reply = QtWidgets.QMessageBox.question(self, "Usuń slave", f"Czy usunąć slave {sid} z konfiguracji?")
        if reply == QtWidgets.QMessageBox.Yes:
            row = self.slave_list.currentRow()
            self.slave_list.takeItem(row)
            with self.handler.lock:
                if sid in self.handler.slaves:
                    del self.handler.slaves[sid]
            # clear tables if no selection
            if self.slave_list.currentItem() is None:
                self.clear_tables()
            self.status(f"Usunięto slave {sid}")

    def on_select_slave(self, cur, prev):
        if cur:
            sid = int(cur.text())
            self.current_slave_label.setText(f"Wybrany slave: {sid}")
            self.pull_from_handler()  # load values into tables
        else:
            self.current_slave_label.setText("Wybrany slave: brak")
            self.clear_tables()

    # ---------- Table helpers ----------
    def clear_tables(self):
        for tbl in (self.holding_table, self.input_table, self.coils_table):
            tbl.table.setRowCount(0)

    def add_holding_row(self):
        tbl = self.holding_table.table
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 0, QtWidgets.QTableWidgetItem("0"))
        tbl.setItem(r, 1, QtWidgets.QTableWidgetItem("0"))

    def add_input_row(self):
        tbl = self.input_table.table
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 0, QtWidgets.QTableWidgetItem("0"))
        tbl.setItem(r, 1, QtWidgets.QTableWidgetItem("0"))

    def add_coil_row(self):
        tbl = self.coils_table.table
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 0, QtWidgets.QTableWidgetItem("0"))
        tbl.setItem(r, 1, QtWidgets.QTableWidgetItem("False"))

    def add_descrete_input_row(self):
        tbl = self.descrete_inputs_table.table
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 0, QtWidgets.QTableWidgetItem("0"))
        tbl.setItem(r, 1, QtWidgets.QTableWidgetItem("False"))

    def remove_selected(self, reg_table: RegistersTable):
        tbl = reg_table.table
        rows = sorted({idx.row() for idx in tbl.selectedIndexes()}, reverse=True)
        for r in rows:
            tbl.removeRow(r)

    # ---------- Pull / Push between GUI <-> handler ----------
    def get_selected_slave(self):
        it = self.slave_list.currentItem()
        if not it:
            return None
        return int(it.text())

    def pull_from_handler(self):
        """Fill tables from handler for selected slave."""
        sid = self.get_selected_slave()
        if sid is None:
            return
        holding = self.handler.get_holding_list(sid)
        input_regs = self.handler.get_input_list(sid)
        coils = self.handler.get_coils_list(sid)

        def populate(tbl_widget, items, bool_vals=False):
            tbl = tbl_widget.table
            tbl.setRowCount(0)
            for addr, val in sorted(items.items()):
                r = tbl.rowCount()
                tbl.insertRow(r)
                tbl.setItem(r, 0, QtWidgets.QTableWidgetItem(str(addr)))
                tbl.setItem(r, 1, QtWidgets.QTableWidgetItem(str(val)))

        populate(self.holding_table, holding)
        populate(self.input_table, input_regs)
        populate(self.coils_table, coils)

    def push_to_handler(self):
        """Read tables and push values to handler for selected slave."""
        sid = self.get_selected_slave()
        if sid is None:
            return
        # holdings
        for r in range(self.holding_table.table.rowCount()):
            a = self.holding_table.table.item(r, 0)
            v = self.holding_table.table.item(r, 1)
            if not a or not v:
                continue
            try:
                addr = int(a.text())
            except Exception:
                addr = 0
            try:
                val = int(v.text())
            except Exception:
                val = 0
            self.handler.set_holding(sid, addr, val & 0xFFFF)
        # inputs
        for r in range(self.input_table.table.rowCount()):
            a = self.input_table.table.item(r, 0)
            v = self.input_table.table.item(r, 1)
            if not a or not v:
                continue
            try:
                addr = int(a.text())
            except Exception:
                addr = 0
            try:
                val = int(v.text())
            except Exception:
                val = 0
            self.handler.set_input(sid, addr, val & 0xFFFF)
        # coils
        for r in range(self.coils_table.table.rowCount()):
            a = self.coils_table.table.item(r, 0)
            v = self.coils_table.table.item(r, 1)
            if not a or not v:
                continue
            try:
                addr = int(a.text())
            except Exception:
                addr = 0
            txt = v.text().strip().lower()
            val = txt in ("1", "true", "t", "yes", "y")
            self.handler.set_coil(sid, addr, val)

    # ---------- Periodic sync tasks ----------
    def periodic_sync_to_handler(self):
        """Periodically push GUI edits to handler for currently selected slave."""
        # We simply push current table content (lightweight)
        try:
            self.push_to_handler()
        except Exception:
            # swallow errors to not spam timer
            pass

    def periodic_refresh_from_handler(self):
        """Periodically read from handler and update visible tables if values changed."""
        sid = self.get_selected_slave()
        if sid is None:
            return
        try:
            # read lists
            holding = self.handler.get_holding_list(sid)
            input_regs = self.handler.get_input_list(sid)
            coils = self.handler.get_coils_list(sid)

            updated = False

            # helper to update a table in-place without breaking user's current edit session too much
            def update_table(tbl_widget, items, fmt=str):
                nonlocal updated
                tbl = tbl_widget.table
                # build mapping addr -> row
                addr_to_row = {}
                for r in range(tbl.rowCount()):
                    a_item = tbl.item(r, 0)
                    if a_item:
                        try:
                            addr_to_row[int(a_item.text())] = r
                        except Exception:
                            pass
                # update existing rows
                for addr, val in items.items():
                    s_val = fmt(val)
                    if addr in addr_to_row:
                        row = addr_to_row[addr]
                        val_item = tbl.item(row, 1)
                        if val_item and val_item.text() != s_val:
                            val_item.setText(s_val)
                            updated = True
                    else:
                        # add new row
                        r = tbl.rowCount()
                        tbl.insertRow(r)
                        tbl.setItem(r, 0, QtWidgets.QTableWidgetItem(str(addr)))
                        tbl.setItem(r, 1, QtWidgets.QTableWidgetItem(s_val))
                        updated = True
                # Optionally remove rows that no longer exist? We'll keep them (user might want to keep)
            update_table(self.holding_table, holding, fmt=lambda x: str(int(x)))
            update_table(self.input_table, input_regs, fmt=lambda x: str(int(x)))
            update_table(self.coils_table, coils, fmt=lambda x: "True" if bool(x) else "False")

            if updated:
                self.status("Odświeżono wartości z handlera")
        except Exception:
            pass

    # ---------- Server control ----------
    def start_server(self):
        if self.server_running:
            self.status("Serwer już działa")
            return
        host = self.input_host.text().strip() or "0.0.0.0"
        port = int(self.input_port.value())
        try:
            # Try to create server with custom data handler
            # Note: pyModbusTCP.ModbusServer may accept 'data_handler' or 'data_bank' depending on version.
            # We'll attempt data_handler first.
            try:
                self.server = ModbusServer(host=host, port=port, data_hdl=self.handler, no_block=True)
            except TypeError:
                # fallback to 'data_bank' name
                self.server = ModbusServer(host=host, port=port, data_bank=self.handler, no_block=True)
            self.server.start()
            self.server_running = True
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.status(f"Serwer uruchomiony na {host}:{port}")
        except Exception as e:
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "Błąd uruchamiania serwera",
                                           f"Nie udało się uruchomić serwera: {e}\n"
                                           "Jeśli masz starszą/niższą wersję pyModbusTCP, "
                                           "sprawdź dokumentację lub podaj wersję biblioteki.")
            self.server = None
            self.server_running = False

    def stop_server(self):
        if not self.server_running or not self.server:
            self.status("Serwer nie działa")
            return
        try:
            self.server.stop()
        except Exception:
            pass
        self.server = None
        self.server_running = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status("Serwer zatrzymany")

    # ---------- Save / Load config ----------
    def save_config(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Zapisz konfigurację", self.config_path, "JSON files (*.json);;All files (*)")
        if not path:
            return
        try:
            data = self.handler.export_all()
            # export keys as strings for JSON friendliness
            dumpable = { str(k): v for k, v in data.items() }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dumpable, f, indent=2)
            print(f"[config] Zapisano: {path}")
            self.status("Zapisano konfigurację: " + path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Błąd zapisu", str(e))

    def load_config(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Wczytaj konfigurację", self.config_path, "JSON files (*.json);;All files (*)")
        if not path:
            return
        try:
            self.load_config_from_path(path)
            self.config_path = path
            print(f"[config] Wczytano: {path}")
            self.status("Wczytano konfigurację: " + path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Błąd wczytywania", str(e))

    def load_config_from_path(self, path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # keys may be strings
        normalized = {}
        for k, v in raw.items():
            normalized[int(k)] = v
        self.handler.import_all(normalized)
        # refresh slave list UI
        self.slave_list.clear()
        for sid in sorted(normalized.keys()):
            self.slave_list.addItem(str(sid))
        # select first
        if self.slave_list.count() > 0:
            self.slave_list.setCurrentRow(0)
        else:
            self.clear_tables()

    # ---------- UI helpers ----------
    def status(self, text: str):
        self.status_label.setText(text)

    def closeEvent(self, event):
        reply = QtWidgets.QMessageBox(self)
        reply.setWindowTitle("Zamknij symulator")
        reply.setText(f"Zapisać zmiany do pliku konfiguracji?\n\n{self.config_path}")
        btn_save = reply.addButton("Zapisz i zamknij", QtWidgets.QMessageBox.AcceptRole)
        btn_discard = reply.addButton("Porzuć zmiany", QtWidgets.QMessageBox.DestructiveRole)
        reply.addButton("Anuluj", QtWidgets.QMessageBox.RejectRole)
        reply.exec()

        clicked = reply.clickedButton()
        if clicked == btn_save:
            try:
                data = self.handler.export_all()
                dumpable = {str(k): v for k, v in data.items()}
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(dumpable, f, indent=2)
                print(f"[config] Zapisano: {self.config_path}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Błąd zapisu", str(e))
                event.ignore()
                return
        elif clicked == btn_discard:
            print(f"[config] Porzucono zmiany, plik niezmieniony: {self.config_path}")
        else:
            event.ignore()
            return

        try:
            if self.server_running and self.server:
                self.server.stop()
        except Exception:
            pass
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Modbus Multi-Slave GUI Simulator")
    parser.add_argument(
        "--config",
        default=None,
        metavar="PLIK",
        help="Ścieżka do pliku konfiguracji JSON (domyślnie: config.json w katalogu skryptu)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Włącz logowanie każdego zapytania Modbus na terminal",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config if args.config else os.path.join(script_dir, "config.json")

    if args.debug:
        print("[debug] Tryb debugowania włączony — każde zapytanie Modbus będzie logowane")

    app = QtWidgets.QApplication(sys.argv)
    if sys.platform == "darwin":
        app.setStyle("macos")

    icon_path = os.path.join(script_dir, "modbus-logo-png.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QtGui.QIcon(icon_path))
    else:
        print(f"[warn] Brak pliku ikony: {icon_path}")

    w = MainWindow(config_path=config_path, debug=args.debug)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()