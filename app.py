import customtkinter as ctk
import threading
import time
import math
import serial
import urllib.request
import ssl
from io import BytesIO
from PIL import Image

# =========================================
# CONFIG & STATE
# =========================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

WASH_CONFIG = [
    {"id": 1, "key": 'NORMAL',   "name": 'Hot',      "mins": 31, "price": 4, "in_temp": 90, "out_temp": 80, "icon_url": "https://img.icons8.com/color/96/fire-element.png"},
    {"id": 2, "key": 'HEAVY',    "name": 'Warm',     "mins": 37, "price": 5, "in_temp": 60, "out_temp": 80, "icon_url": "https://img.icons8.com/color/96/thermometer.png"},
    {"id": 3, "key": 'QUICK',    "name": 'Cold',     "mins": 39, "price": 6, "in_temp": 30, "out_temp": 50, "icon_url": "https://img.icons8.com/color/96/snowflake.png"},
    {"id": 4, "key": 'DELICATE', "name": 'Delicate', "mins": 43, "price": 6, "in_temp": 30, "out_temp": 50, "icon_url": "https://img.icons8.com/color/96/leaf.png"},
    {"id": 5, "key": 'EXTRA',    "name": 'Speed',    "mins": 5,  "price": 8, "in_temp": 60, "out_temp": 90, "icon_url": "https://img.icons8.com/color/96/electricity.png"} 
]

# =========================================
# NATIVE MODBUS SLAVE ENGINE
# =========================================
class NativeModbusSlave:
    def __init__(self, port, baudrate=9600, slave_id=1):
        self.port = port
        self.baudrate = baudrate
        self.slave_id = slave_id
        self.registers = {i: 0 for i in range(1101)}
        self.ser = None
        self.running = False
        self.buffer = []

    def crc16(self, data):
        crc = 0xFFFF
        for pos in data:
            crc ^= pos
            for _ in range(8):
                if (crc & 1) != 0:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return crc

    def start(self):
        self.running = True
        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()

    def _run_server(self):
        try:
            self.ser = serial.Serial(self.port, baudrate=self.baudrate, timeout=0.05)
            print(f"✅ Modbus Engine Started on {self.port} at {self.baudrate} bps")
        except Exception as e:
            print(f"❌ Cannot open port {self.port}: {e}")
            return

        while self.running:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.read(self.ser.in_waiting)
                    self.buffer.extend(data)
                    self._process_buffer()
            except Exception as e:
                pass
            time.sleep(0.01)

    def _process_buffer(self):
        while len(self.buffer) >= 8:
            if self.buffer[0] != self.slave_id:
                self.buffer.pop(0)
                continue
                
            func = self.buffer[1]
            if func == 0x03 or func == 0x06:
                expected_len = 8
            elif func == 0x10:
                expected_len = 7 + self.buffer[6] + 2 if len(self.buffer) >= 7 else 999
            else:
                expected_len = 0
                
            if expected_len == 0:
                self.buffer.pop(0)
                continue
                
            if len(self.buffer) < expected_len:
                break 
                
            frame = self.buffer[:expected_len]
            crc_received = (frame[-1] << 8) | frame[-2]
            crc_calculated = self.crc16(frame[:-2])
            
            if crc_calculated == crc_received:
                self._handle_request(frame, func)
                self.buffer = self.buffer[expected_len:]
            else:
                self.buffer.pop(0)

    def _handle_request(self, req, func):
        resp = []
        if func == 0x03:
            start = (req[2] << 8) | req[3]
            count = (req[4] << 8) | req[5]
            if start + count > 1100:
                resp = [self.slave_id, func | 0x80, 0x02]
            else:
                resp = [self.slave_id, func, count * 2]
                for i in range(count):
                    val = self.registers.get(start + i, 0)
                    resp.append((val >> 8) & 0xFF)
                    resp.append(val & 0xFF)
                    
        elif func == 0x06:
            addr = (req[2] << 8) | req[3]
            val = (req[4] << 8) | req[5]
            self.registers[addr] = val
            resp = req[:] 
            
        elif func == 0x10:
            start = (req[2] << 8) | req[3]
            count = (req[4] << 8) | req[5]
            for i in range(count):
                idx = 7 + (i * 2)
                val = (req[idx] << 8) | req[idx + 1]
                self.registers[start + i] = val
            resp = [self.slave_id, func, req[2], req[3], req[4], req[5]]
            
        if resp:
            crc = self.crc16(resp)
            resp.append(crc & 0xFF)
            resp.append((crc >> 8) & 0xFF)
            try:
                self.ser.write(bytes(resp))
            except:
                pass

# =========================================
# MAIN APP (UI & LOGIC)
# =========================================
class WashingMachineApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Washing Machine - Pi 5")
        self.geometry("1024x600")
        self.attributes('-fullscreen', True) 
        
        # --- App State ---
        self.current_screen = 'menu'
        self.selected_mode = 'NORMAL'
        self.job_details = {}
        self.total_coins_recorded = 5000
        self.coins_in_box = 1200
        self.total_seconds_remaining = 0
        self.progress_pct = 0
        self.current_step = 0
        self.timer_event = None
        self.current_menu_page = 0 
        self.is_processing_payment = False
        
        # --- Load Images ---
        self.images = self.load_all_images()
        
        # --- Modbus Setup ---
        self.port_name = '/dev/ttyAMA0' 
        self.modbus = NativeModbusSlave(port=self.port_name, baudrate=9600, slave_id=1)
        self.init_registers()
        self.modbus.start()
        
        # --- UI Build ---
        self.setup_ui()
        self.update_job_details()
        self.switch_screen('menu')
        
        # --- Start Core Loops ---
        self.sync_loop()
        self.timer_loop() # แก้ไขบั๊กเวลาค้าง สตาร์ทลูปนับเวลาตรงนี้!

    # =========================================
    # IMAGE LOADER UTILS
    # =========================================
    def load_image_from_url(self, url, size):
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            raw_data = urllib.request.urlopen(req, timeout=5, context=ctx).read()
            image = Image.open(BytesIO(raw_data))
            return ctk.CTkImage(light_image=image, dark_image=image, size=size)
        except Exception as e:
            print(f"⚠️ Could not load image from {url}: {e}")
            return None

    def load_all_images(self):
        print("⏳ Loading images...")
        imgs = {
            "logo": self.load_image_from_url("https://placehold.co/300x80/1a1a2e/00d4ff.png?text=WASH+SIMULATOR", (200, 50)),
            "qr_code": self.load_image_from_url("https://placehold.co/200x200/ffffff/000000.png?text=QR+CODE", (180, 180)),
        }
        for prog in WASH_CONFIG:
            imgs[prog['key']] = self.load_image_from_url(prog['icon_url'], (70, 70))
        print("✅ Image loading complete.")
        return imgs

    # =========================================
    # MODAL & DATASTORE UTILS
    # =========================================
    def init_registers(self):
        for i in range(302):
            self.set_reg(i, 0)
        
        self.set_reg(100, 15) 
        self.set_reg(115, len(WASH_CONFIG)) 
        self.set_reg(140, 4) 
        
        self.set_reg(20, 1) 
        self.set_reg(21, 2) 
        self.set_reg(22, 0) 
        self.set_reg(28, 1) 
        self.set_reg(31, 0) 
        self.set_reg(32, self.total_coins_recorded) 
        self.set_reg(33, self.coins_in_box) 
        
        for i, prog in enumerate(WASH_CONFIG):
            self.set_reg(274 + i, prog['price'])
            self.set_reg(240 + i, prog['mins'])
            self.set_reg(153 + i, prog['in_temp'])
            self.set_reg(160 + i, prog['out_temp'])

    def set_reg(self, address, value):
        self.modbus.registers[address] = int(value)

    def get_reg(self, address):
        return self.modbus.registers.get(address, 0)

    # =========================================
    # UI SETUP
    # =========================================
    def setup_ui(self):
        self.main_container = ctk.CTkFrame(self, fg_color="#1a1a2e") 
        self.main_container.pack(fill="both", expand=True)
        
        self.screens_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.screens_frame.pack(fill="both", expand=True)
        
        self.build_menu_screen()
        self.build_payment_screen()
        self.build_process_screen()
        self.build_finish_screen()

    # -----------------------------------------
    # 1. MAIN MENU SCREEN (PAGINATION)
    # -----------------------------------------
    def build_menu_screen(self):
        self.frame_menu = ctk.CTkFrame(self.screens_frame, fg_color="transparent")
        
        header_frame = ctk.CTkFrame(self.frame_menu, fg_color="transparent", height=80)
        header_frame.pack(fill="x", padx=40, pady=(20, 0))
        
        if self.images.get("logo"):
            logo_lbl = ctk.CTkLabel(header_frame, text="", image=self.images["logo"])
        else:
            logo_lbl = ctk.CTkLabel(header_frame, text="WASH SIMULATOR", font=("Arial", 30, "bold"), text_color="#00d4ff")
        logo_lbl.pack(side="left")

        self.btn_menu_start = ctk.CTkButton(header_frame, text="START / PAY", font=("Arial", 20, "bold"), fg_color="#e94560", hover_color="#c81d49", command=self.go_payment)
        self.btn_menu_start.pack(side="right")

        self.lbl_menu_coin = ctk.CTkLabel(header_frame, text="Coin : 0", font=("Arial", 24, "bold"), text_color="#00d4ff", fg_color="#16213e", corner_radius=10, padx=20, pady=10)
        self.lbl_menu_coin.pack(side="right", padx=(0, 20))

        content_frame = ctk.CTkFrame(self.frame_menu, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=40, pady=20)

        # สร้างปุ่ม ซ้าย ขวา
        self.btn_prev = ctk.CTkButton(content_frame, text="<", width=60, font=("Arial", 40, "bold"), fg_color="#16213e", hover_color="#00d4ff", text_color="white", command=self.prev_menu_page)
        self.btn_prev.pack(side="left", fill="y", pady=10)

        self.cards_container = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.cards_container.pack(side="left", fill="both", expand=True, padx=20)

        self.btn_next = ctk.CTkButton(content_frame, text=">", width=60, font=("Arial", 40, "bold"), fg_color="#16213e", hover_color="#00d4ff", text_color="white", command=self.next_menu_page)
        self.btn_next.pack(side="right", fill="y", pady=10)
        
        self.menu_cards = []

    def prev_menu_page(self):
        if self.current_menu_page > 0:
            self.current_menu_page -= 1
            self.generate_menu_cards()
            self.render_menu()

    def next_menu_page(self):
        max_per_page = self.get_reg(140)
        if max_per_page <= 0: max_per_page = 4
        total_items = self.get_reg(115)
        
        max_pages = math.ceil(total_items / max_per_page)
        if self.current_menu_page < max_pages - 1:
            self.current_menu_page += 1
            self.generate_menu_cards()
            self.render_menu()
            
    def auto_switch_menu_page(self, target_prog_id):
        max_per_page = self.get_reg(140)
        if max_per_page <= 0: max_per_page = 4
        
        idx = next((i for i, p in enumerate(WASH_CONFIG) if p['id'] == target_prog_id), 0)
        target_page = idx // max_per_page
        
        if self.current_menu_page != target_page or len(self.menu_cards) == 0:
            self.current_menu_page = target_page
            self.generate_menu_cards()
        
    def generate_menu_cards(self):
        for widget in self.cards_container.winfo_children():
            widget.destroy()
        self.menu_cards.clear()
        
        max_per_page = self.get_reg(140)
        if max_per_page <= 0: max_per_page = 4
        total_items = self.get_reg(115)
        
        start_idx = self.current_menu_page * max_per_page
        end_idx = start_idx + max_per_page
        display_progs = WASH_CONFIG[start_idx:end_idx]
            
        for prog in display_progs:
            card = ctk.CTkFrame(self.cards_container, width=200, height=350, corner_radius=15, fg_color="#16213e")
            card.pack(side="left", expand=True, padx=10, pady=10)
            card.pack_propagate(False)
            
            icon_img = self.images.get(prog['key'])
            if icon_img:
                icon_lbl = ctk.CTkLabel(card, text="", image=icon_img)
            else:
                icon_lbl = ctk.CTkLabel(card, text="[ICON]")
            icon_lbl.pack(pady=(20, 10))
            
            name_lbl = ctk.CTkLabel(card, text=prog['name'], font=("Arial", 26, "bold"), text_color="white")
            name_lbl.pack()
            
            info_frame = ctk.CTkFrame(card, fg_color="transparent")
            info_frame.pack(pady=10)
            
            time_lbl = ctk.CTkLabel(info_frame, text=f"{prog['mins']} Min", font=("Arial", 18), text_color="#00d4ff")
            time_lbl.pack()
            
            display_price = prog['price'] * 10
            price_lbl = ctk.CTkLabel(info_frame, text=f"{display_price} ฿", font=("Arial", 22, "bold"), text_color="#e94560")
            price_lbl.pack()
            
            btn = ctk.CTkButton(card, text="SELECT", font=("Arial", 18, "bold"), height=45,
                                fg_color="#0f3460", hover_color="#00d4ff", text_color="white",
                                command=lambda p=prog: self.card_btn_clicked(p))
            btn.pack(side="bottom", pady=20, fill="x", padx=20)
            
            def bind_click(widget, p=prog):
                widget.bind("<Button-1>", lambda event, p_prog=p: self.select_mode_by_id(p_prog['id']))
            
            bind_click(card)
            bind_click(icon_lbl)
            bind_click(name_lbl)
            
            self.menu_cards.append({
                "key": prog['key'],
                "frame": card,
                "btn": btn
            })

        bg_color = "#1a1a2e"
        max_pages = math.ceil(total_items / max_per_page)
        
        if self.current_menu_page > 0:
            self.btn_prev.configure(state="normal", fg_color="#16213e", text_color="white")
        else:
            self.btn_prev.configure(state="disabled", fg_color="transparent", text_color=bg_color)
            
        if self.current_menu_page < max_pages - 1:
            self.btn_next.configure(state="normal", fg_color="#16213e", text_color="white")
        else:
            self.btn_next.configure(state="disabled", fg_color="transparent", text_color=bg_color)

    def select_mode_by_id(self, mode_id):
        prog = next((p for p in WASH_CONFIG if p['id'] == mode_id), None)
        if prog:
            self.selected_mode = prog['key']
            self.update_job_details()
            self.render_menu()

    def card_btn_clicked(self, prog):
        if self.selected_mode == prog['key']:
            self.go_payment()
        else:
            self.select_mode_by_id(prog['id'])

    # -----------------------------------------
    # 2. PAYMENT SCREEN
    # -----------------------------------------
    def build_payment_screen(self):
        self.frame_payment = ctk.CTkFrame(self.screens_frame, fg_color="#1a1a2e")
        
        header_frame = ctk.CTkFrame(self.frame_payment, fg_color="transparent", height=80)
        header_frame.pack(fill="x", padx=40, pady=(20, 10))
        
        btn_back = ctk.CTkButton(header_frame, text="CANCEL / BACK", width=150, height=50, fg_color="transparent", border_width=2, border_color="#e94560", text_color="#e94560",
                                 font=("Arial", 18, "bold"), command=lambda: self.switch_screen('menu'))
        btn_back.pack(side="left")

        self.lbl_pay_remain = ctk.CTkLabel(header_frame, text="REMAINING: 0 ฿", font=("Arial", 28, "bold"), text_color="#e94560", bg_color="#1a1a2e")
        self.lbl_pay_remain.pack(side="right")
        
        content_frame = ctk.CTkFrame(self.frame_payment, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=40, pady=10)
        
        left_frame = ctk.CTkFrame(content_frame, fg_color="#16213e", corner_radius=20, width=400)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        ctk.CTkLabel(left_frame, text="TOTAL PRICE", font=("Arial", 18, "bold"), text_color="gray").pack(pady=(40, 0))
        self.lbl_pay_total = ctk.CTkLabel(left_frame, text="0", font=("Arial", 100, "bold"), text_color="white")
        self.lbl_pay_total.pack()
        
        right_frame = ctk.CTkFrame(content_frame, fg_color="#0f3460", corner_radius=20)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))
        
        ctk.CTkLabel(right_frame, text="PAID AMOUNT", font=("Arial", 18, "bold"), text_color="#00d4ff").pack(pady=(40, 0))
        self.lbl_pay_paid = ctk.CTkLabel(right_frame, text="0", font=("Arial", 100, "bold"), text_color="#00d4ff")
        self.lbl_pay_paid.pack()
        
        ctk.CTkButton(right_frame, text="SIMULATE COIN (+1)", height=60, font=("Arial", 20, "bold"), fg_color="#00d4ff", text_color="#1a1a2e",
                      command=lambda: self.add_money_test(1)).pack(pady=20, padx=40, fill="x")

        self.overlay_success = ctk.CTkFrame(self.frame_payment, fg_color="#00d4ff", corner_radius=20, width=400, height=200)
        self.lbl_success = ctk.CTkLabel(self.overlay_success, text="✔ STARTING...", font=("Arial", 40, "bold"), text_color="#1a1a2e")
        self.lbl_success.place(relx=0.5, rely=0.5, anchor="center")

    # -----------------------------------------
    # 3. PROCESS & FINISH SCREENS
    # -----------------------------------------
    def build_process_screen(self):
        self.frame_process = ctk.CTkFrame(self.screens_frame, fg_color="#1a1a2e")
        self.progress_bar = ctk.CTkProgressBar(self.frame_process, width=600, height=40, corner_radius=20, progress_color="#00d4ff", fg_color="#16213e")
        self.progress_bar.pack(pady=(100, 20))
        self.progress_bar.set(0)
        self.lbl_proc_time = ctk.CTkLabel(self.frame_process, text="00:00", font=("Arial", 120, "bold"), text_color="white")
        self.lbl_proc_time.pack()
        self.lbl_proc_status = ctk.CTkLabel(self.frame_process, text="WASHING...", font=("Arial", 30, "bold"), text_color="#00d4ff")
        self.lbl_proc_status.pack(pady=20)
        
        ctk.CTkButton(self.frame_process, text="STOP", height=50, width=150, font=("Arial", 20, "bold"), fg_color="transparent", 
                      border_width=2, border_color="#e94560", text_color="#e94560", command=self.request_cancel_test).pack(side="bottom", pady=40, anchor="e", padx=40)

    def build_finish_screen(self):
        self.frame_finish = ctk.CTkFrame(self.screens_frame, fg_color="#00d4ff")
        ctk.CTkLabel(self.frame_finish, text="COMPLETE", font=("Arial", 80, "bold"), text_color="#1a1a2e").pack(expand=True)
        ctk.CTkLabel(self.frame_finish, text="Please collect your clothes", font=("Arial", 30), text_color="#1a1a2e").pack(pady=(0, 100))

    # =========================================
    # UI LOGIC & TRANSITIONS
    # =========================================
    def switch_screen(self, screen_name):
        self.current_screen = screen_name
        self.frame_menu.pack_forget()
        self.frame_payment.pack_forget()
        self.frame_process.pack_forget()
        self.frame_finish.pack_forget()
        self.overlay_success.place_forget() 
        self.is_processing_payment = False
        
        if screen_name == 'menu':
            target_id = next((p['id'] for p in WASH_CONFIG if p['key'] == self.selected_mode), 1)
            self.auto_switch_menu_page(target_id)
            self.render_menu()
            self.frame_menu.pack(fill="both", expand=True)
        elif screen_name == 'payment':
            self.frame_payment.pack(fill="both", expand=True)
        elif screen_name == 'process':
            self.frame_process.pack(fill="both", expand=True)
        elif screen_name == 'finish':
            self.frame_finish.pack(fill="both", expand=True)

    def render_menu(self):
        for card_data in self.menu_cards:
            is_active = (self.selected_mode == card_data['key'])
            card_data['btn'].configure(text="START" if is_active else "SELECT", fg_color="#e94560" if is_active else "#0f3460")
            card_data['frame'].configure(border_width=2 if is_active else 0, border_color="#e94560" if is_active else "#16213e")
        
        current_credit = self.get_reg(31) 
        self.lbl_menu_coin.configure(text=f"Coin : {current_credit}")

    def update_job_details(self):
        prog = next((p for p in WASH_CONFIG if p['key'] == self.selected_mode), WASH_CONFIG[0])
        idx = prog['id'] - 1
        
        self.job_details = {
            'id': prog['id'], 
            'price': self.get_reg(274 + idx) or prog['price'], 
            'mins': self.get_reg(240 + idx) or prog['mins'], 
            'temp': self.get_reg(153 + idx) or prog['in_temp'], 
            'name': prog['name']
        }

    def go_payment(self):
        self.update_job_details()
        self.render_payment()
        self.switch_screen('payment')

    def render_payment(self):
        current_coins = self.get_reg(31) 
        required_coins = self.job_details.get('price', 0)
        
        display_current_baht = current_coins * 10
        display_required_baht = required_coins * 10
        rem_baht = max(0, display_required_baht - display_current_baht)
        
        self.lbl_pay_total.configure(text=str(display_required_baht))
        self.lbl_pay_paid.configure(text=str(display_current_baht))
        self.lbl_pay_remain.configure(text=f"REMAINING: {rem_baht} ฿")
        
        # ปรับปรุง Auto-Start ให้ทำงานเมื่อเงินครบ
        if current_coins >= required_coins and required_coins > 0:
            self.overlay_success.place(relx=0.5, rely=0.5, anchor="center")
            if not self.is_processing_payment:
                self.is_processing_payment = True
                # โชว์คำว่า STARTING... ค้างไว้ 1 วินาที แล้วสั่ง Address 1 ทำงานเลย
                self.after(1000, lambda: self.set_reg(1, 1))

    def add_money_test(self, coin_count):
        new_val = self.get_reg(31) + coin_count
        self.set_reg(31, new_val)
        self.set_reg(37, new_val)
        self.total_coins_recorded += coin_count
        self.coins_in_box += coin_count
        if self.current_screen == 'payment':
            self.render_payment()

    def request_cancel_test(self):
        self.set_reg(3, 1) 

    # =========================================
    # CORE LOGIC (TIMER UPDATE)
    # =========================================
    def timer_loop(self):
        if self.current_screen == 'process' and self.total_seconds_remaining > 0:
            self.total_seconds_remaining -= 1
            
            m = math.floor(self.total_seconds_remaining / 60)
            s = self.total_seconds_remaining % 60
            self.lbl_proc_time.configure(text=f"{m:02d}:{s:02d}")
            
            # ป้องกัน ZeroDivisionError ด้วยการกำหนดค่าต่ำสุดคือ 1 วินาที
            total = max(1, self.job_details.get('mins', 30) * 60)
            
            self.progress_pct = ((total - self.total_seconds_remaining) / total)
            self.progress_bar.set(self.progress_pct)
            
            if self.total_seconds_remaining > total * 0.7:
                self.lbl_proc_status.configure(text="WASHING...")
                self.current_step = 1
            elif self.total_seconds_remaining > total * 0.3:
                self.lbl_proc_status.configure(text="RINSING...")
                self.current_step = 2
            else:
                self.lbl_proc_status.configure(text="SPINNING...")
                self.current_step = 3
                    
        elif self.current_screen == 'process' and self.total_seconds_remaining <= 0:
            self.switch_screen('finish')
            self.after(5000, lambda: self.switch_screen('menu'))
            
        self.timer_event = self.after(1000, self.timer_loop)

    # =========================================
    # PURE MODBUS SYNC 
    # =========================================
    def sync_loop(self):
        if not self.modbus.running:
            self.after(50, self.sync_loop)
            return

        cmd_start = self.get_reg(1)
        cmd_stop = self.get_reg(3)
        cmd_coin_in = self.get_reg(4)
        cmd_prog = self.get_reg(5)

        if cmd_start: self.set_reg(1, 0)
        if cmd_stop: self.set_reg(3, 0)
        if cmd_prog: self.set_reg(5, 0)
        if cmd_coin_in > 0: self.set_reg(4, 0)

        if cmd_coin_in > 0:
            current_balance = self.get_reg(31) 
            new_balance = current_balance + cmd_coin_in
            self.set_reg(31, new_balance) 
            self.set_reg(37, new_balance) 
            self.total_coins_recorded += cmd_coin_in
            self.coins_in_box += cmd_coin_in

            if self.current_screen == 'payment':
                self.render_payment()
            elif self.current_screen == 'menu':
                self.go_payment()

        if cmd_prog > 0:
            if self.current_screen == 'menu':
                self.select_mode_by_id(cmd_prog)

        if cmd_start == 1:
            if self.current_screen == 'menu': 
                self.go_payment()
            elif self.current_screen == 'payment': 
                req_coins = self.job_details.get('price', 0)
                cur_coins = self.get_reg(31)
                if cur_coins >= req_coins:
                    self.set_reg(31, cur_coins - req_coins)
                    self.set_reg(37, cur_coins - req_coins)
                    self.total_seconds_remaining = self.job_details.get('mins', 30) * 60
                    self.switch_screen('process')

        if cmd_stop == 1:
            if self.current_screen == 'process': 
                self.total_seconds_remaining = 0
                self.switch_screen('menu')
            elif self.current_screen == 'payment': 
                self.switch_screen('menu')

        if self.current_screen == 'menu':
            prog = next((p for p in WASH_CONFIG if p['key'] == self.selected_mode), WASH_CONFIG[0])
            self.set_reg(28, prog['id'])
            
            if self.lbl_menu_coin.cget("text") != f"Coin : {self.get_reg(31)}":
                self.render_menu()

        self.update_job_details()
        
        prog_id = self.job_details.get('id', 1)
        current_price = self.job_details.get('price', 4)
        current_mins = self.job_details.get('mins', 45)
        current_temp = self.job_details.get('temp', 30)
        
        status_val = 3 if self.current_screen == 'process' else 1
        door_val = 3 if self.current_screen == 'process' else 2
        time_total_sec = self.total_seconds_remaining if self.current_screen == 'process' else 0
        
        remain_hr = math.floor(time_total_sec / 3600)
        remain_min = math.floor((time_total_sec % 3600) / 60)
        remain_sec = time_total_sec % 60
        step_num = self.current_step if self.current_screen == 'process' else 0

        wallet_balance = self.get_reg(31) 

        self.set_reg(20, status_val)
        self.set_reg(21, door_val)
        self.set_reg(22, 0) 

        if self.current_screen == 'process':
            self.set_reg(20, 3)
            self.set_reg(21, 3)
            self.set_reg(23, remain_hr)
            self.set_reg(24, remain_min)
            self.set_reg(25, remain_sec)
            self.set_reg(26, remain_min) # Min
            self.set_reg(27, remain_sec) # Sec
        else:
            self.set_reg(20, 1)
            self.set_reg(21, 1)
            self.set_reg(23, 0)
            self.set_reg(24, current_mins)
            self.set_reg(25, 0)
            self.set_reg(26, 0)
            self.set_reg(27, 0)

        self.set_reg(28, prog_id)
        self.set_reg(29, step_num)
        self.set_reg(30, current_price) 
        self.set_reg(31, wallet_balance)
        self.set_reg(32, self.total_coins_recorded)
        self.set_reg(33, self.coins_in_box)
        self.set_reg(34, prog_id)
        
        if self.current_screen == 'process':
            if remain_min < 50: self.set_reg(35, 1)
            if remain_min < 31: self.set_reg(35, 2)
            if remain_min < 30: self.set_reg(35, 3)
            if remain_min < 28: self.set_reg(35, 4)
            if remain_min < 20: self.set_reg(35, 5)
            if remain_min < 15: self.set_reg(35, 6)
            if remain_min < 10: self.set_reg(35, 7)
            if remain_min < 3:  self.set_reg(35, 8)
            if remain_min < 1:  self.set_reg(35, 0)
        else:
            self.set_reg(35, 0)

        self.set_reg(36, current_price)  
        self.set_reg(37, wallet_balance) 

        self.after(50, self.sync_loop)

if __name__ == "__main__":
    app = WashingMachineApp()
    app.mainloop()
