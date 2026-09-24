# -*- coding: utf-8 -*-
import asyncio
import json
import os
import threading
import time
import tkinter as tk
import httpx
from pathlib import Path
from tkinter import ttk, messagebox

APP_NAME = "QQ关键词自动回复"
BASE = Path(os.environ.get("APPDATA", Path.home())) / "QQKeywordAutoReply"
BASE.mkdir(parents=True, exist_ok=True)
CONFIG = BASE / "config.json"

DEFAULT = {
    "app_id": "",
    "app_secret": "",
    "keywords": ["有意", "有意愿", "有意者", "有意向"],
    "reply": "1",
    "cooldown": 3,
    "groups": []
}

def load_config():
    if not CONFIG.exists():
        save_config(DEFAULT)
        return dict(DEFAULT)
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        out = dict(DEFAULT)
        out.update(data)
        return out
    except Exception:
        return dict(DEFAULT)

def save_config(data):
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

class BotRunner:
    def __init__(self, logger, status):
        self.logger = logger
        self.status = status
        self.loop = None
        self.ws = None
        self.api = None
        self.http_client = None
        self.running = False
        self.last_reply = 0.0

    def log(self, s):
        self.logger(s)

    def start(self, cfg):
        if self.running:
            return
        if not cfg["app_id"] or not cfg["app_secret"]:
            raise ValueError("请先填写 AppID 和 AppSecret。")
        self.running = True
        self.status(True)
        threading.Thread(target=self._thread_main, args=(cfg,), daemon=True).start()

    def stop(self):
        self.running = False
        if self.loop and self.ws:
            try:
                self.loop.call_soon_threadsafe(self.ws.stop)
            except Exception:
                pass
        self.status(False)
        self.log("机器人已停止。")

    def _thread_main(self, cfg):
        try:
            from qqbot_agent_sdk import QQApiClient, QQWebSocket, WSCallbacks, EventParser

            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            # 当前官方 SDK 示例要求先创建 httpx.AsyncClient，
            # 再通过 QQApiClient.setup() 注入 HTTP 客户端。
            self.http_client = httpx.AsyncClient(timeout=60.0)

            self.api = QQApiClient(
                app_id=cfg["app_id"],
                client_secret=cfg["app_secret"],
                log_tag="KeywordReply"
            )
            self.api.setup(self.http_client)

            parser = EventParser()

            async def on_message(event_type, raw):
                try:
                    event = parser.parse(event_type, raw)
                    if not event:
                        return
                    text = (event.content or "").strip()
                    if not text or event.chat_scope != "group":
                        return

                    keywords = sorted(
                        [x.strip() for x in cfg["keywords"] if x.strip()],
                        key=len, reverse=True
                    )
                    hit = next((k for k in keywords if k in text), None)
                    if not hit:
                        return

                    groups = [x.strip() for x in cfg["groups"] if x.strip()]
                    if groups and event.chat_id not in groups:
                        return

                    now = time.time()
                    if now - self.last_reply < max(0, float(cfg["cooldown"])):
                        self.log(f"命中「{hit}」，但仍在冷却时间内。")
                        return

                    await self.api.send_text(
                        "group", event.chat_id, cfg["reply"],
                        reply_to=event.message_id
                    )
                    self.last_reply = now
                    self.log(f"命中「{hit}」 → 已回复「{cfg['reply']}」")
                except Exception as e:
                    self.log("处理消息失败：" + str(e))

            # 当前 qqbot-agent-sdk 版本要求这些 WSCallbacks 参数。
            # 暂不使用 Resume，会话信息由 SDK 重新建立。
            self.ws = QQWebSocket(
                callbacks=WSCallbacks(
                    on_message_event=on_message,
                    get_token=self.api.ensure_token_sync,
                    get_gateway_url=self.api.get_gateway_url_sync,
                    get_session=lambda: (None, None),
                    set_session=lambda session_id, seq: None,
                    set_heartbeat_interval=lambda interval: self.log(
                        f"QQ 心跳间隔：{interval} 秒"
                    ),
                    clear_token=self.api.clear_token,
                    fail_pending=lambda reason: self.log(
                        "待处理请求失败：" + str(reason)
                    ),
                    on_connected=lambda: self.log("✓ QQ WebSocket 已连接"),
                    on_disconnected=lambda: self.log("⚠ QQ WebSocket 已断开"),
                    on_fatal_error=lambda code, msg: self.log(
                        f"✗ 致命错误 [{code}] {msg}"
                    ),
                    on_heartbeat_ack=lambda: None,
                ),
                log_tag="KeywordReply"
            )

            self.loop.run_until_complete(self.api.ensure_token())
            gateway = self.loop.run_until_complete(self.api.get_gateway_url())
            self.log("正在连接 QQ 开放平台……")
            self.ws.start(gateway, self.loop)
            self.log("机器人已启动，等待群消息……")
            self.loop.run_forever()

        except Exception as e:
            self.log("启动失败：" + str(e))
        finally:
            self.running = False
            self.status(False)
            try:
                if self.loop and self.http_client:
                    self.loop.run_until_complete(
                        self.http_client.aclose()
                    )
            except Exception:
                pass

            try:
                if self.loop:
                    self.loop.close()
            except Exception:
                pass

            self.http_client = None

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("720x690")
        self.root.resizable(False, False)
        self.cfg = load_config()
        self.bot = BotRunner(self.log, self.set_status)

        outer = ttk.Frame(root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_NAME, font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w")
        ttk.Label(outer, text="检测群消息中的关键词，命中后自动回复指定内容",
                  foreground="#666").pack(anchor="w", pady=(3, 14))

        auth = ttk.LabelFrame(outer, text="QQ 机器人配置", padding=12)
        auth.pack(fill="x")
        ttk.Label(auth, text="AppID").grid(row=0, column=0, sticky="w", pady=5)
        self.app_id = ttk.Entry(auth, width=65)
        self.app_id.grid(row=0, column=1, sticky="ew", padx=8)
        self.app_id.insert(0, self.cfg["app_id"])
        ttk.Label(auth, text="AppSecret").grid(row=1, column=0, sticky="w", pady=5)
        self.secret = ttk.Entry(auth, width=65, show="•")
        self.secret.grid(row=1, column=1, sticky="ew", padx=8)
        self.secret.insert(0, self.cfg["app_secret"])

        rules = ttk.LabelFrame(outer, text="自动回复规则", padding=12)
        rules.pack(fill="x", pady=12)
        ttk.Label(rules, text="关键词（每行一个）").pack(anchor="w")
        self.keywords = tk.Text(rules, height=5, font=("Microsoft YaHei UI", 10))
        self.keywords.pack(fill="x", pady=(5, 8))
        self.keywords.insert("1.0", "\n".join(self.cfg["keywords"]))

        row = ttk.Frame(rules)
        row.pack(fill="x")
        ttk.Label(row, text="回复内容").pack(side="left")
        self.reply = ttk.Entry(row, width=12)
        self.reply.pack(side="left", padx=(8, 24))
        self.reply.insert(0, self.cfg["reply"])
        ttk.Label(row, text="冷却秒数").pack(side="left")
        self.cooldown = ttk.Entry(row, width=8)
        self.cooldown.pack(side="left", padx=8)
        self.cooldown.insert(0, str(self.cfg["cooldown"]))

        ttk.Label(rules, text="指定群 ID（每行一个；留空表示不限制）").pack(anchor="w", pady=(12, 0))
        self.groups = tk.Text(rules, height=3, font=("Microsoft YaHei UI", 10))
        self.groups.pack(fill="x", pady=(5, 0))
        self.groups.insert("1.0", "\n".join(self.cfg["groups"]))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(2, 12))
        ttk.Button(buttons, text="保存配置", command=self.save).pack(side="left")
        ttk.Button(buttons, text="启动机器人", command=self.start).pack(side="left", padx=8)
        ttk.Button(buttons, text="停止机器人", command=self.stop).pack(side="left")
        self.status = ttk.Label(buttons, text="● 已停止", foreground="#a33")
        self.status.pack(side="right")

        box = ttk.LabelFrame(outer, text="运行日志", padding=8)
        box.pack(fill="both", expand=True)
        self.logbox = tk.Text(box, height=15, state="disabled", bg="#111", fg="#ddd",
                              font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True)
        ttk.Label(outer,
                  text="AppSecret 只保存在本机 %APPDATA%\QQKeywordAutoReply\config.json，请勿发给他人。",
                  foreground="#777").pack(anchor="w", pady=(8, 0))

    def get_cfg(self):
        try:
            cooldown = max(0, float(self.cooldown.get().strip() or "3"))
        except ValueError:
            raise ValueError("冷却秒数必须是数字。")
        return {
            "app_id": self.app_id.get().strip(),
            "app_secret": self.secret.get().strip(),
            "keywords": [x.strip() for x in self.keywords.get("1.0", "end").splitlines() if x.strip()],
            "reply": self.reply.get(),
            "cooldown": cooldown,
            "groups": [x.strip() for x in self.groups.get("1.0", "end").splitlines() if x.strip()]
        }

    def save(self):
        try:
            cfg = self.get_cfg()
            save_config(cfg)
            self.cfg = cfg
            self.log("配置已保存。")
        except Exception as e:
            messagebox.showerror("配置错误", str(e))

    def start(self):
        try:
            cfg = self.get_cfg()
            save_config(cfg)
            self.cfg = cfg
            self.bot.start(cfg)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    def stop(self):
        self.bot.stop()

    def set_status(self, running):
        self.root.after(0, lambda: self.status.config(
            text="● 运行中" if running else "● 已停止",
            foreground="#14804a" if running else "#a33"
        ))

    def log(self, text):
        def add():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.root.after(0, add)

    def close(self):
        self.bot.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
