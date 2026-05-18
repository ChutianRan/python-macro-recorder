import json
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from pynput import keyboard, mouse


APP_DIR = Path(__file__).resolve().parent
RECORDS_FILE = APP_DIR / "macro_records.json"

CONTROL_KEYS = {
    keyboard.Key.f9,
    keyboard.Key.f10,
    keyboard.Key.f12,
}


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        if key.char is not None:
            return {"kind": "char", "value": key.char}
        return {"kind": "vk", "value": key.vk}
    return {"kind": "special", "value": key.name}


def data_to_key(data):
    if data["kind"] == "char":
        return keyboard.KeyCode.from_char(data["value"])
    if data["kind"] == "vk":
        return keyboard.KeyCode.from_vk(data["value"])
    return getattr(keyboard.Key, data["value"])


def button_to_name(button):
    return button.name


def name_to_button(name):
    return getattr(mouse.Button, name)


class MacroStore:
    def __init__(self, path):
        self.path = path
        self.records = []
        self.load()

    def load(self):
        if not self.path.exists():
            self.records = []
            return
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            self.records = data.get("records", [])
        except (json.JSONDecodeError, OSError):
            self.records = []

    def save(self):
        data = {"version": 1, "records": self.records}
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def add(self, name, events):
        record = {
            "id": str(int(time.time() * 1000)),
            "name": name,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "events": events,
        }
        self.records.append(record)
        self.save()
        return record

    def delete(self, record_id):
        self.records = [record for record in self.records if record["id"] != record_id]
        self.save()


class MacroApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Python 鼠标键盘宏")
        self.geometry("760x520")
        self.minsize(700, 460)

        self.store = MacroStore(RECORDS_FILE)
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()

        self.recording = False
        self.playing = False
        self.record_start_time = 0.0
        self.record_events = []
        self.last_move_time = 0.0
        self.mouse_listener = None
        self.keyboard_listener = None
        self.global_hotkey_listener = None
        self.play_thread = None
        self.stop_playback = threading.Event()

        self.status_text = tk.StringVar(value="准备就绪")
        self.selected_record_id = None
        self.window_bounds = (0, 0, 0, 0)

        self._build_ui()
        self._refresh_record_list()
        self._start_global_hotkeys()
        self.bind("<Configure>", self._update_window_bounds)
        self.after(100, self._update_window_bounds)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(14, 14, 14, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(4, weight=1)

        self.start_button = ttk.Button(top, text="开始记录 (F9)", command=self.start_recording)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.finish_button = ttk.Button(top, text="完成记录 (F10)", command=self.finish_recording, state="disabled")
        self.finish_button.grid(row=0, column=1, padx=(0, 8))

        self.play_once_button = ttk.Button(top, text="运行一次", command=lambda: self.play_selected(loop=False))
        self.play_once_button.grid(row=0, column=2, padx=(0, 8))

        self.play_loop_button = ttk.Button(top, text="无限重复", command=lambda: self.play_selected(loop=True))
        self.play_loop_button.grid(row=0, column=3, padx=(0, 8))

        self.stop_button = ttk.Button(top, text="停止运行 (F12)", command=self.stop_running, state="disabled")
        self.stop_button.grid(row=0, column=4, sticky="w")

        main = ttk.Frame(self, padding=(14, 6, 14, 8))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="已保存记录").grid(row=0, column=0, sticky="w")

        columns = ("name", "events", "created_at")
        self.record_tree = ttk.Treeview(main, columns=columns, show="headings", selectmode="browse")
        self.record_tree.heading("name", text="名称")
        self.record_tree.heading("events", text="事件数")
        self.record_tree.heading("created_at", text="创建时间")
        self.record_tree.column("name", width=310)
        self.record_tree.column("events", width=90, anchor="center")
        self.record_tree.column("created_at", width=180, anchor="center")
        self.record_tree.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.record_tree.bind("<<TreeviewSelect>>", self._on_record_select)

        scrollbar = ttk.Scrollbar(main, orient="vertical", command=self.record_tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.record_tree.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.Frame(self, padding=(14, 0, 14, 14))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self.delete_button = ttk.Button(bottom, text="删除选中记录", command=self.delete_selected)
        self.delete_button.grid(row=0, column=0, sticky="w")

        ttk.Label(
            bottom,
            text="热键：F9 开始记录，F10 完成记录，F12 停止运行。录制时会忽略本窗口内的鼠标点击。",
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))

        status = ttk.Label(self, textvariable=self.status_text, relief="sunken", anchor="w", padding=(8, 4))
        status.grid(row=3, column=0, sticky="ew")

    def _refresh_record_list(self):
        for item in self.record_tree.get_children():
            self.record_tree.delete(item)

        for record in self.store.records:
            self.record_tree.insert(
                "",
                "end",
                iid=record["id"],
                values=(record["name"], len(record["events"]), record["created_at"]),
            )
        self._update_buttons()

    def _on_record_select(self, _event=None):
        selection = self.record_tree.selection()
        self.selected_record_id = selection[0] if selection else None
        self._update_buttons()

    def _update_buttons(self):
        has_selection = self.selected_record_id is not None
        idle = not self.recording and not self.playing

        self.start_button.configure(state="normal" if idle else "disabled")
        self.finish_button.configure(state="normal" if self.recording else "disabled")
        self.play_once_button.configure(state="normal" if idle and has_selection else "disabled")
        self.play_loop_button.configure(state="normal" if idle and has_selection else "disabled")
        self.delete_button.configure(state="normal" if idle and has_selection else "disabled")
        self.stop_button.configure(state="normal" if self.playing else "disabled")

    def _update_window_bounds(self, _event=None):
        self.window_bounds = (
            self.winfo_rootx(),
            self.winfo_rooty(),
            self.winfo_rootx() + self.winfo_width(),
            self.winfo_rooty() + self.winfo_height(),
        )

    def start_recording(self):
        if self.recording or self.playing:
            return

        self.recording = True
        self.record_events = []
        self.record_start_time = time.perf_counter()
        self.last_move_time = 0.0
        self.status_text.set("正在记录输入，按 F10 完成记录")
        self._update_buttons()

        self.mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def _start_global_hotkeys(self):
        self.global_hotkey_listener = keyboard.Listener(on_press=self._on_global_hotkey)
        self.global_hotkey_listener.start()

    def _on_global_hotkey(self, key):
        if key == keyboard.Key.f9 and not self.recording and not self.playing:
            self.after(0, self.start_recording)
        elif key == keyboard.Key.f10 and self.recording:
            self.after(0, self.finish_recording)
        elif key == keyboard.Key.f12 and self.playing:
            self.stop_playback.set()

    def finish_recording(self):
        if not self.recording:
            return

        self.recording = False
        self._stop_record_listeners()

        events = list(self.record_events)
        self.record_events = []

        if not events:
            self.status_text.set("没有录到任何可保存的输入")
            self._update_buttons()
            return

        name = simpledialog.askstring("保存记录", "给这段宏起个名字：", parent=self)
        if not name:
            name = time.strftime("宏记录 %Y-%m-%d %H-%M-%S")

        self.store.add(name.strip(), events)
        self.status_text.set(f"已保存：{name.strip()}，共 {len(events)} 个事件")
        self._refresh_record_list()
        self._update_buttons()

    def _stop_record_listeners(self):
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

    def _record_time(self):
        return time.perf_counter() - self.record_start_time

    def _add_event(self, event):
        if not self.recording:
            return
        event["time"] = round(self._record_time(), 5)
        self.record_events.append(event)

    def _is_inside_window(self, x, y):
        left, top, right, bottom = self.window_bounds
        return left <= x <= right and top <= y <= bottom

    def _on_mouse_move(self, x, y):
        if not self.recording or self._is_inside_window(x, y):
            return

        now = time.perf_counter()
        if now - self.last_move_time < 0.03:
            return
        self.last_move_time = now
        self._add_event({"type": "mouse_move", "x": x, "y": y})

    def _on_mouse_click(self, x, y, button, pressed):
        if not self.recording or self._is_inside_window(x, y):
            return
        self._add_event(
            {
                "type": "mouse_click",
                "x": x,
                "y": y,
                "button": button_to_name(button),
                "pressed": pressed,
            }
        )

    def _on_mouse_scroll(self, x, y, dx, dy):
        if not self.recording or self._is_inside_window(x, y):
            return
        self._add_event({"type": "mouse_scroll", "x": x, "y": y, "dx": dx, "dy": dy})

    def _on_key_press(self, key):
        if key == keyboard.Key.f10:
            self.after(0, self.finish_recording)
            return False
        if key in CONTROL_KEYS:
            return
        self._add_event({"type": "key", "action": "press", "key": key_to_data(key)})

    def _on_key_release(self, key):
        if key in CONTROL_KEYS:
            return
        self._add_event({"type": "key", "action": "release", "key": key_to_data(key)})

    def get_selected_record(self):
        if not self.selected_record_id:
            return None
        for record in self.store.records:
            if record["id"] == self.selected_record_id:
                return record
        return None

    def play_selected(self, loop):
        if self.recording or self.playing:
            return

        record = self.get_selected_record()
        if not record:
            messagebox.showinfo("提示", "请先选择一个记录。")
            return

        self.playing = True
        self.stop_playback.clear()
        mode = "无限重复" if loop else "运行一次"
        self.status_text.set(f"正在{mode}：{record['name']}，按 F12 可停止")
        self._update_buttons()

        self.play_thread = threading.Thread(
            target=self._play_worker,
            args=(record, loop),
            daemon=True,
        )
        self.play_thread.start()

    def _play_worker(self, record, loop):
        keyboard_stop_listener = keyboard.Listener(on_press=self._on_playback_hotkey)
        keyboard_stop_listener.start()

        try:
            while not self.stop_playback.is_set():
                self._play_events(record["events"])
                if not loop:
                    break
        finally:
            keyboard_stop_listener.stop()
            self.after(0, self._playback_finished)

    def _on_playback_hotkey(self, key):
        if key == keyboard.Key.f12:
            self.stop_playback.set()
            return False
        return True

    def _play_events(self, events):
        previous_time = 0.0
        for event in events:
            if self.stop_playback.is_set():
                return

            wait_for = max(0.0, event["time"] - previous_time)
            previous_time = event["time"]
            if self.stop_playback.wait(wait_for):
                return

            self._execute_event(event)

    def _execute_event(self, event):
        event_type = event["type"]

        if event_type == "mouse_move":
            self.mouse_controller.position = (event["x"], event["y"])
            return

        if event_type == "mouse_click":
            self.mouse_controller.position = (event["x"], event["y"])
            button = name_to_button(event["button"])
            if event["pressed"]:
                self.mouse_controller.press(button)
            else:
                self.mouse_controller.release(button)
            return

        if event_type == "mouse_scroll":
            self.mouse_controller.position = (event["x"], event["y"])
            self.mouse_controller.scroll(event["dx"], event["dy"])
            return

        if event_type == "key":
            key = data_to_key(event["key"])
            if event["action"] == "press":
                self.keyboard_controller.press(key)
            else:
                self.keyboard_controller.release(key)

    def _playback_finished(self):
        self.playing = False
        self.stop_playback.clear()
        self.status_text.set("运行已停止")
        self._update_buttons()

    def stop_running(self):
        self.stop_playback.set()
        self.status_text.set("正在停止运行...")

    def delete_selected(self):
        record = self.get_selected_record()
        if not record:
            return
        confirmed = messagebox.askyesno("删除记录", f"确定删除“{record['name']}”吗？")
        if not confirmed:
            return
        self.store.delete(record["id"])
        self.selected_record_id = None
        self.status_text.set(f"已删除：{record['name']}")
        self._refresh_record_list()

    def _on_close(self):
        if self.recording:
            self.recording = False
            self._stop_record_listeners()
        if self.playing:
            self.stop_playback.set()
        if self.global_hotkey_listener:
            self.global_hotkey_listener.stop()
        self.destroy()


if __name__ == "__main__":
    app = MacroApp()
    app.mainloop()
