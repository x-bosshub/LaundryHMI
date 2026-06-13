import customtkinter as ctk
import threading
import time
import math
import urllib.request
import ssl
from io import BytesIO
from PIL import Image
import os
import concurrent.futures
import hashlib

# =========================================
# CONFIG & STATE
# =========================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ปิดระบบ Auto Scaling ที่มักจะทำ UI เพี้ยนบน Raspberry Pi
ctk.set_window_scaling(1.0)
ctk.set_widget_scaling(1.0)

WASH_CONFIG = [
    {"id": 1, "key": 'QUICK',   "name": 'ซักด่วน',      "sub": 'น้ำอุณหภูมิปกติ', "mins": 30, "price": 3, "in_temp": 30, "out_temp": 50, "icon_url": "https://img.icons8.com/color/96/snowflake.png"},
    {"id": 2, "key": 'WARM',    "name": 'ซักน้ำอุ่น',     "sub": 'ถนอมเนื้อผ้า',   "mins": 40, "price": 4, "in_temp": 60, "out_temp": 80, "icon_url": "https://img.icons8.com/color/96/thermometer.png"},
    {"id": 3, "key": 'HOT',     "name": 'ซักน้ำร้อน',     "sub": 'ฆ่าเชื้อโรค',   "mins": 50, "price": 5, "in_temp": 90, "out_temp": 80, "icon_url": "https://img.icons8.com/?size=160&id=TpMuKyoLjXII&format=png"},
    {"id": 4, "key": 'BLANKET', "name": 'ซักผ้าห่ม',      "sub": 'ผืนใหญ่พิเศษ',  "mins": 60, "price": 6, "in_temp": 30, "out_temp": 50, "icon_url": "https://img.icons8.com/?size=96&id=pUk0TsB8HdE3&format=png"},
    {"id": 5, "key": 'EXTRA',    "name": 'ซักด่วนพิเศษ',   "sub": 'เร่งเวลาการซัก', "mins": 15, "price": 2, "in_temp": 60, "out_temp": 90, "icon_url": "https://img.icons8.com/?size=160&id=69682&format=png"} 
]

# Color Palette (WashLover Theme)
BG_NAVY = "#1a1f2b"
CARD_WHITE = "#ffffff"
TEXT_DARK = "#333333"
TEXT_MUTED = "#888888"
BTN_BLUE = "#2d6dec"
SUCCESS_GREEN = "#22c55e"
DANGER_RED = "#ef4444"

# เตรียม Directory สำหรับ Cache รูปภาพ
CACHE_DIR = "assets"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# =========================================
# MAIN APP (UI & LOGIC ONLY)
# =========================================
class WashingMachineApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("WashLover Ecosystem - UI Mockup")
        self.geometry("1024x600")
        self.attributes('-fullscreen', True) 
        self.bind("<Escape>", lambda e: self.destroy())
        
        # --- App State ---
        self.current_screen = 'menu'
        self.selected_mode = 'QUICK'
        self.job_details = {}
        self.total_coins_recorded = 5000
        self.coins_in_box = 1200
        self.total_seconds_remaining = 0
        self.progress_pct = 0
        self.current_step = 0
        self.timer_event = None
        self.current_menu_page = 0 
        self.is_processing_payment = False
        self.images = {}
        
        # --- Reward State ---
        self.phone_number = ""
        self.reward_timeout = 15
        
        # --- Animation State ---
        self.anim_frames = ["🌀  กำลังซักผ้า .  ", "🌊  กำลังซักผ้า .. ", "🫧  กำลังซักผ้า ..."]
        self.anim_idx = 0
        self.anim_event = None
        
        # --- Mock Registers Setup ---
        self.registers = {}
        self.init_registers()
        
        # --- UI Build ---
        self.setup_ui()
        self.update_job_details()
        self.switch_screen('menu')
        
        # --- Start Core Loops ---
        self.timer_loop()
        
        # --- Start Background Image Loading ---
        threading.Thread(target=self.bg_load_images, daemon=True).start()

    # =========================================
    # IMAGE LOADER UTILS (Cached & Concurrent)
    # =========================================
    def load_image_from_url(self, url, size):
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        filepath = os.path.join(CACHE_DIR, f"{url_hash}.png")

        try:
            if os.path.exists(filepath):
                image = Image.open(filepath)
                return ctk.CTkImage(light_image=image, dark_image=image, size=size)

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            raw_data = urllib.request.urlopen(req, timeout=5.0, context=ctx).read()
            image = Image.open(BytesIO(raw_data))
            image.save(filepath, format="PNG")
            
            return ctk.CTkImage(light_image=image, dark_image=image, size=size)
            
        except Exception as e:
            fallback_image = Image.new("RGB", size, (220, 220, 220))
            return ctk.CTkImage(light_image=fallback_image, dark_image=fallback_image, size=size)

    def bg_load_images(self):
        tasks = [
            ("logo", "https://app.washlover.com/static/logo-washlover.png", (220, 130)),
            ("qr_code", "https://payment.washlover.com/generate?chl=00020101021230810016A00000067701011201150107536000315010214KB0000022388850320APIC1779263190951UMO31690016A00000067701011301030040214KB0000022388850420APIC1779263190951UMO5303764540510.005802TH6304AC1A", (220, 220)),
            ("duck_icon", "https://app.washlover.com/static/washlover-icon.png", (150, 150))
        ]
        
        for prog in WASH_CONFIG:
            tasks.append((prog['key'], prog['icon_url'], (70, 70)))
        
        loaded_imgs = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_key = {
                executor.submit(self.load_image_from_url, url, size): key 
                for key, url, size in tasks
            }
            
            for future in concurrent.futures.as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    loaded_imgs[key] = future.result()
                except Exception:
                    pass
        
        self.images = loaded_imgs
        self.after(0, self.apply_loaded_images)

    def apply_loaded_images(self):
        if "logo" in self.images and hasattr(self, 'logo_lbl'):
            self.logo_lbl.configure(image=self.images["logo"], text="")
        
        if "qr_code" in self.images and hasattr(self, 'qr_lbl'):
            self.qr_lbl.configure(image=self.images["qr_code"], text="")
            
        if "duck_icon" in self.images and hasattr(self, 'duck_lbl'):
            self.duck_lbl.configure(image=self.images["duck_icon"], text="")
            
        self.generate_menu_cards()

    # =========================================
    # MOCK DATASTORE UTILS
    # =========================================
    def init_registers(self):
        self.registers = {i: 0 for i in range(1101)}
        self.set_reg(100, 15) 
        self.set_reg(115, len(WASH_CONFIG)) 
        self.set_reg(140, 4) 
        
        self.set_reg(20, 1) 
        self.set_reg(21, 2) 
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
        self.registers[address] = int(value)

    def get_reg(self, address):
        return self.registers.get(address, 0)

    # =========================================
    # UI SETUP
    # =========================================
    def setup_ui(self):
        self.main_container = ctk.CTkFrame(self, fg_color=BG_NAVY) 
        self.main_container.pack(fill="both", expand=True)
        
        self.screens_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.screens_frame.pack(fill="both", expand=True)
        
        self.build_menu_screen()
        self.build_payment_screen()
        self.build_reward_screen()
        self.build_process_screen()
        self.build_finish_screen()

    # -----------------------------------------
    # 1. MAIN MENU SCREEN
    # -----------------------------------------
    def build_menu_screen(self):
        self.frame_menu = ctk.CTkFrame(self.screens_frame, fg_color="transparent")
        
        # Header
        header_frame = ctk.CTkFrame(self.frame_menu, fg_color="transparent", height=80)
        header_frame.pack(fill="x", padx=40, pady=(30, 10))
        
        self.logo_lbl = ctk.CTkLabel(header_frame, text="WashLover", font=("Arial", 35, "bold"), text_color=CARD_WHITE)
        self.logo_lbl.pack(side="left")

        self.lbl_coin_info = ctk.CTkLabel(header_frame, text=f"เหรียญ : {self.get_reg(31)}", font=("Arial", 22, "bold"), text_color=CARD_WHITE, fg_color=BTN_BLUE, corner_radius=10, padx=20, pady=5)
        self.lbl_coin_info.pack(side="right")

        # Content Area
        content_frame = ctk.CTkFrame(self.frame_menu, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Slider Previous Button
        self.btn_prev = ctk.CTkButton(content_frame, text="<", font=("Arial", 40, "bold"), width=50, fg_color="transparent", hover_color="#273043", text_color=TEXT_MUTED, command=self.prev_menu_page)
        self.btn_prev.pack(side="left", fill="y")

        # Cards Container
        self.cards_container = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.cards_container.pack(side="left", fill="both", expand=True)
        
        # Slider Next Button
        self.btn_next = ctk.CTkButton(content_frame, text=">", font=("Arial", 40, "bold"), width=50, fg_color="transparent", hover_color="#273043", text_color=TEXT_MUTED, command=self.next_menu_page)
        self.btn_next.pack(side="right", fill="y")
        
        # Admin Footer
        ctk.CTkLabel(self.frame_menu, text="Admin", font=("Arial", 12), text_color="#374151").place(relx=0.98, rely=0.98, anchor="se")

        self.menu_cards = []
        self.generate_menu_cards()

    def prev_menu_page(self):
        if self.current_menu_page > 0:
            self.current_menu_page -= 1
            self.generate_menu_cards()

    def next_menu_page(self):
        max_per_page = self.get_reg(140)
        if max_per_page <= 0:
            max_per_page = 4
        total_items = self.get_reg(115)
        
        max_pages = math.ceil(total_items / max_per_page)
        if self.current_menu_page < max_pages - 1:
            self.current_menu_page += 1
            self.generate_menu_cards()

    def generate_menu_cards(self):
        for widget in self.cards_container.winfo_children():
            widget.destroy()
        self.menu_cards.clear()
        
        max_per_page = self.get_reg(140)
        if max_per_page <= 0:
            max_per_page = 4
            
        start_idx = self.current_menu_page * max_per_page
        end_idx = start_idx + max_per_page
        display_progs = WASH_CONFIG[start_idx:end_idx]
        
        for prog in display_progs:
            card_wrapper = ctk.CTkFrame(self.cards_container, fg_color="transparent")
            card_wrapper.pack(side="left", expand=True, fill="both", padx=10, pady=10)
            
            is_active = (self.selected_mode == prog['key'])
            card_border_color = BTN_BLUE if is_active else CARD_WHITE
            
            card = ctk.CTkFrame(card_wrapper, corner_radius=15, fg_color=CARD_WHITE, border_width=8, border_color=card_border_color)
            card.pack(expand=True, fill="both")
            
            # Icon Setup
            icon_img = self.images.get(prog['key'])
            if icon_img:
                icon_lbl = ctk.CTkLabel(card, text="", image=icon_img)
            else:
                icon_lbl = ctk.CTkLabel(card, text="Loading", text_color=TEXT_MUTED)
            icon_lbl.pack(pady=(35, 10))
            
            # Title & Subtitle Setup
            name_lbl = ctk.CTkLabel(card, text=prog['name'], font=("Arial", 30, "bold"), text_color=TEXT_DARK)
            name_lbl.pack()
            sub_lbl = ctk.CTkLabel(card, text=prog['sub'], font=("Arial", 18), text_color=TEXT_MUTED)
            sub_lbl.pack(pady=(0, 15))
            
            # Info Frame
            info_frame = ctk.CTkFrame(card, fg_color="transparent")
            info_frame.pack(expand=True)
            
            time_lbl = ctk.CTkLabel(info_frame, text=f"⏱ {prog['mins']} นาที", font=("Arial", 22, "bold"), text_color=BTN_BLUE)
            time_lbl.pack()
            
            display_price = prog['price'] * 10
            price_lbl = ctk.CTkLabel(info_frame, text=f"{display_price} บาท", font=("Arial", 22, "bold"), text_color=BTN_BLUE)
            price_lbl.pack(pady=(5, 0))
            
            # Action Button Setup
            btn_text = "ชำระเงิน" if is_active else "เลือกโปรแกรม"
            btn_color = SUCCESS_GREEN if is_active else BTN_BLUE
            btn_hover = "#16a34a" if is_active else "#1e4e9d"
            
            btn = ctk.CTkButton(card, text=btn_text, font=("Arial", 20, "bold"), height=55, corner_radius=10,
                                fg_color=btn_color, hover_color=btn_hover, text_color=CARD_WHITE,
                                command=lambda p=prog: self.card_btn_clicked(p))
            btn.pack(side="bottom", pady=25, fill="x", padx=20)
            
            # Bind Events
            def bind_click(widget, p=prog):
                widget.bind("<Button-1>", lambda event, p_prog=p: self.select_mode_by_id(p_prog['id']))
            
            bind_click(card)
            bind_click(icon_lbl)
            bind_click(name_lbl)
            bind_click(sub_lbl)
            
            self.menu_cards.append({
                "key": prog['key'],
                "frame": card,
                "btn": btn,
                "icon_lbl": icon_lbl  
            })

        # Update Navigation State
        total_items = self.get_reg(115)
        max_pages = math.ceil(total_items / max_per_page)
        
        if self.current_menu_page > 0:
            self.btn_prev.configure(state="normal")
        else:
            self.btn_prev.configure(state="disabled")
            
        if self.current_menu_page < max_pages - 1:
            self.btn_next.configure(state="normal")
        else:
            self.btn_next.configure(state="disabled")

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
        self.frame_payment = ctk.CTkFrame(self.screens_frame, fg_color="transparent")
        
        left_sidebar = ctk.CTkFrame(self.frame_payment, fg_color="transparent", width=250)
        left_sidebar.pack(side="left", fill="y", padx=30, pady=20)
        
        self.duck_lbl = ctk.CTkLabel(left_sidebar, text="[LOGO]", text_color=TEXT_MUTED)
        self.duck_lbl.pack(pady=(60, 10))
        
        self.lbl_pay_mode = ctk.CTkLabel(left_sidebar, text="ซักด่วน", font=("Arial", 40, "bold"), text_color=CARD_WHITE)
        self.lbl_pay_mode.pack(pady=10)
        
        main_card = ctk.CTkFrame(self.frame_payment, corner_radius=25, fg_color=CARD_WHITE)
        main_card.pack(side="left", fill="both", expand=True, padx=20, pady=50)
        
        top_info = ctk.CTkFrame(main_card, fg_color="transparent", height=100)
        top_info.pack(fill="x", padx=40, pady=(30, 20))
        
        time_frame = ctk.CTkFrame(top_info, fg_color="transparent")
        time_frame.pack(side="left", expand=True)
        ctk.CTkLabel(time_frame, text="⏱ เวลา", font=("Arial", 22), text_color=TEXT_MUTED).pack()
        self.lbl_pay_time = ctk.CTkLabel(time_frame, text="30 นาที", font=("Arial", 28, "bold"), text_color=TEXT_DARK)
        self.lbl_pay_time.pack()
        
        divider = ctk.CTkFrame(top_info, width=2, height=60, fg_color="#e0e0e0")
        divider.pack(side="left")
        
        price_frame = ctk.CTkFrame(top_info, fg_color="transparent")
        price_frame.pack(side="left", expand=True)
        ctk.CTkLabel(price_frame, text="ราคา", font=("Arial", 22), text_color=TEXT_MUTED).pack()
        self.lbl_pay_total_ratio = ctk.CTkLabel(price_frame, text="0/30 บาท", font=("Arial", 32, "bold"), text_color=BTN_BLUE)
        self.lbl_pay_total_ratio.pack()
        
        ctk.CTkFrame(main_card, height=2, fg_color="#e0e0e0").pack(fill="x", padx=40)
        
        content_box = ctk.CTkFrame(main_card, fg_color="transparent")
        content_box.pack(fill="both", expand=True, padx=40, pady=20)
        
        qr_frame = ctk.CTkFrame(content_box, fg_color="transparent")
        qr_frame.pack(side="left", expand=True)
        self.qr_lbl = ctk.CTkLabel(qr_frame, text="[QR CODE]", text_color=TEXT_MUTED)
        self.qr_lbl.pack()
        
        inst_frame = ctk.CTkFrame(content_box, fg_color="transparent")
        inst_frame.pack(side="right", expand=True)
        ctk.CTkLabel(inst_frame, text="หยอดเหรียญ หรือ สแกนจ่าย", font=("Arial", 30, "bold"), text_color=TEXT_DARK).pack(pady=20)
        
        self.lbl_pay_coins = ctk.CTkLabel(inst_frame, text="เหรียญสะสม: 0 / 3 เหรียญ\n(ระบบนับ 1 เหรียญ = 10 บาท)", font=("Arial", 22), text_color=DANGER_RED)
        self.lbl_pay_coins.pack(pady=20)

        btn_back = ctk.CTkButton(main_card, text="< กลับไปเลือกใหม่", font=("Arial", 22, "bold"), width=200, height=60, corner_radius=25,
                                 fg_color="#f0f0f0", hover_color="#e0e0e0", text_color=TEXT_DARK, command=lambda: self.switch_screen('menu'))
        btn_back.pack(side="bottom", anchor="e", padx=40, pady=30)
        
        ctk.CTkButton(self.frame_payment, text="จำลองหยอดเหรียญ +10", fg_color="#f59e0b", hover_color="#d97706", text_color="white",
                      command=lambda: self.add_money_test(1)).place(relx=0.02, rely=0.95, anchor="sw")

    # -----------------------------------------
    # 3. REWARD SCREEN (NUMPAD) - ล็อกขนาดป้องกันการขยับ
    # -----------------------------------------
    def build_reward_screen(self):
        self.frame_reward = ctk.CTkFrame(self.screens_frame, fg_color="transparent")
        
        center_wrapper = ctk.CTkFrame(self.frame_reward, fg_color="transparent")
        center_wrapper.place(relx=0.5, rely=0.5, anchor="center")
        
        header = ctk.CTkFrame(center_wrapper, fg_color="transparent")
        header.pack(fill="x", pady=(0, 30))
        ctk.CTkLabel(header, text="✔ ชำระเงินสำเร็จแล้ว!", font=("Arial", 32, "bold"), text_color=SUCCESS_GREEN).pack(anchor="w")
        
        # ถอดคำสั่ง expand=True ออก เพื่อไม่ให้เนื้อหายืดตามอิสระ
        content = ctk.CTkFrame(center_wrapper, fg_color="transparent")
        content.pack(pady=10)
        
        # Left Side (Input Display) - กำหนดขนาดกว้าง 450 สูง 400 แบบล็อกตัว
        left_side = ctk.CTkFrame(content, fg_color="transparent", width=480, height=400)
        left_side.pack_propagate(False) # คำสั่งนี้ห้ามให้ขนาดเปลี่ยนตามของข้างใน
        left_side.pack(side="left", padx=(0, 40))
        
        ctk.CTkLabel(left_side, text="รับคะแนนสะสม", font=("Arial", 45, "bold"), text_color=CARD_WHITE).pack(anchor="w", pady=(0, 10))
        ctk.CTkLabel(left_side, text="กรุณากรอกเบอร์โทรของท่านเพื่อรับแต้ม\nหรือกดข้ามเพื่อเริ่มทำงานทันที", font=("Arial", 22), text_color=TEXT_MUTED, justify="left").pack(anchor="w", pady=(0, 30))
        
        # ล็อกช่องแสดงเบอร์โทรศัพท์ให้กว้างเต็มกรอบเสมอ
        self.lbl_phone_input = ctk.CTkLabel(left_side, text="000-000-0000", font=("Arial", 50, "bold"), text_color=CARD_WHITE,
                                            fg_color="#273043", corner_radius=10, height=100)
        self.lbl_phone_input.pack(fill="x", pady=(0, 20))
        
        self.lbl_reward_timer = ctk.CTkLabel(left_side, text="ระบบจะข้ามอัตโนมัติใน 15 วินาที", font=("Arial", 22), text_color="#f59e0b")
        self.lbl_reward_timer.pack(anchor="w", pady=(0, 20))
        
        btn_skip = ctk.CTkButton(left_side, text="⏭ ข้ามการสะสมคะแนน", font=("Arial", 26, "bold"), height=70, corner_radius=10,
                                 fg_color="#374151", hover_color="#4b5563", text_color=CARD_WHITE, command=self.start_washing_process)
        btn_skip.pack(fill="x")
        
        # Right Side (Numpad) - กำหนดขนาดกว้าง 380 สูง 400 แบบล็อกตัว
        numpad_frame = ctk.CTkFrame(content, fg_color="transparent", width=380, height=400)
        numpad_frame.pack_propagate(False) # ห้ามขนาดเปลี่ยน
        numpad_frame.pack(side="right")
        
        for i in range(4): numpad_frame.grid_rowconfigure(i, weight=1)
        for i in range(3): numpad_frame.grid_columnconfigure(i, weight=1)
        
        buttons = [
            ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
            ('ลบ', 3, 0), ('0', 3, 1), ('ตกลง', 3, 2)
        ]
        
        for (text, row, col) in buttons:
            color = "#374151"
            hover = "#4b5563"
            txt_col = CARD_WHITE
            cmd = lambda t=text: self.numpad_click(t)
            
            if text == 'ลบ':
                color = DANGER_RED
                hover = "#c53030"
            elif text == 'ตกลง':
                color = SUCCESS_GREEN
                hover = "#16a34a"
            
            btn = ctk.CTkButton(numpad_frame, text=text, font=("Arial", 28, "bold"), corner_radius=15,
                                fg_color=color, hover_color=hover, text_color=txt_col, command=cmd)
            btn.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

    def numpad_click(self, key):
        self.reward_timeout = 15 
        
        if key == 'ลบ':
            self.phone_number = self.phone_number[:-1]
        elif key == 'ตกลง':
            if len(self.phone_number) >= 10:
                print(f"✅ โทรศัพท์ที่สะสมแต้ม: {self.phone_number}")
                self.start_washing_process()
        else:
            if len(self.phone_number) < 10:
                self.phone_number += key
                
        self.update_phone_display()

    def update_phone_display(self):
        raw = self.phone_number
        formatted = ""
        for i, char in enumerate(raw):
            if i == 3 or i == 6:
                formatted += "-"
            formatted += char
            
        if not formatted:
            formatted = "000-000-0000"
            self.lbl_phone_input.configure(text_color=TEXT_MUTED)
        else:
            self.lbl_phone_input.configure(text_color=CARD_WHITE)
            
        self.lbl_phone_input.configure(text=formatted)

    def start_washing_process(self):
        req_coins = self.job_details.get('price', 0)
        cur_coins = self.get_reg(31)
        
        if cur_coins >= req_coins:
            self.set_reg(31, cur_coins - req_coins)
            self.set_reg(37, cur_coins - req_coins)
        
        self.total_seconds_remaining = self.job_details.get('mins', 30) * 60
        self.switch_screen('process')

    # -----------------------------------------
    # 4. PROCESS SCREEN
    # -----------------------------------------
    def build_process_screen(self):
        self.frame_process = ctk.CTkFrame(self.screens_frame, fg_color="transparent")
        
        left_side = ctk.CTkFrame(self.frame_process, fg_color="transparent")
        left_side.pack(side="left", fill="both", expand=True, pady=40, padx=50)
        
        ctk.CTkLabel(left_side, text="เวลาคงเหลือโดยประมาณ", font=("Arial", 28, "bold"), text_color=TEXT_MUTED).pack(pady=(80, 20))
        
        time_container = ctk.CTkFrame(left_side, fg_color="transparent")
        time_container.pack(expand=True)
        
        self.lbl_proc_min = ctk.CTkLabel(time_container, text="30", font=("Arial", 200, "bold"), text_color="#38bdf8")
        self.lbl_proc_min.pack(side="left", anchor="s")
        ctk.CTkLabel(time_container, text="นาที", font=("Arial", 40, "bold"), text_color=TEXT_MUTED).pack(side="left", anchor="s", padx=(15,0), pady=(0, 45))
        
        self.progress_bar = ctk.CTkProgressBar(left_side, height=20, corner_radius=10, progress_color=SUCCESS_GREEN, fg_color="#273043")
        self.progress_bar.pack(fill="x", padx=40, pady=(30, 15))
        self.progress_bar.set(0)
        
        self.lbl_proc_anim = ctk.CTkLabel(left_side, text="🌀  กำลังซักผ้า .  ", font=("Arial", 30, "bold"), text_color="#38bdf8")
        self.lbl_proc_anim.pack(pady=(10, 0))
        
        self.lbl_proc_status = ctk.CTkLabel(left_side, text="ระบบกำลังประเมินน้ำหนักผ้า", font=("Arial", 20), text_color=TEXT_MUTED)
        self.lbl_proc_status.pack()

        right_sidebar = ctk.CTkFrame(self.frame_process, width=350, corner_radius=20, fg_color="#1e2532")
        right_sidebar.pack_propagate(False)
        right_sidebar.pack(side="right", fill="y", padx=30, pady=30)
        
        ctk.CTkLabel(right_sidebar, text="สถานะ", font=("Arial", 26, "bold"), text_color=CARD_WHITE).pack(pady=40)
        
        self.step_frames = []
        steps = ["ซักผ้า", "ล้างน้ำ", "ปั่นหมาด"]
        for text in steps:
            frame = ctk.CTkFrame(right_sidebar, height=80, corner_radius=15, fg_color="#273043")
            frame.pack_propagate(False)
            frame.pack(fill="x", padx=25, pady=10)
            lbl = ctk.CTkLabel(frame, text=text, font=("Arial", 26, "bold"), text_color=TEXT_MUTED)
            lbl.pack(expand=True, anchor="w", padx=30)
            self.step_frames.append({"frame": frame, "lbl": lbl})
            
        btn_cancel = ctk.CTkButton(right_sidebar, text="ยกเลิกฉุกเฉิน", font=("Arial", 24, "bold"), height=70, corner_radius=15,
                                   fg_color=DANGER_RED, hover_color="#c53030", text_color=CARD_WHITE, command=self.show_cancel_confirmation)
        btn_cancel.pack(side="bottom", fill="x", padx=25, pady=30)
        
        self.cancel_modal = ctk.CTkFrame(self.frame_process, width=600, height=300, corner_radius=20, fg_color=CARD_WHITE, border_width=2, border_color=DANGER_RED)
        
        ctk.CTkLabel(self.cancel_modal, text="⚠️ ยืนยันการยกเลิกฉุกเฉิน?", font=("Arial", 35, "bold"), text_color=DANGER_RED).place(relx=0.5, rely=0.3, anchor="center")
        ctk.CTkLabel(self.cancel_modal, text="กระบวนการซักจะหยุดลงทันที และไม่สามารถขอคืนเงินได้", font=("Arial", 20), text_color=TEXT_DARK).place(relx=0.5, rely=0.5, anchor="center")
        
        btn_no = ctk.CTkButton(self.cancel_modal, text="กลับไปทำงานต่อ", font=("Arial", 22, "bold"), width=220, height=60, corner_radius=10,
                               fg_color="#e5e7eb", hover_color="#d1d5db", text_color=TEXT_DARK, command=self.hide_cancel_confirmation)
        btn_no.place(relx=0.3, rely=0.75, anchor="center")
        
        btn_yes = ctk.CTkButton(self.cancel_modal, text="ยืนยันหยุดทำงาน", font=("Arial", 22, "bold"), width=220, height=60, corner_radius=10,
                                fg_color=DANGER_RED, hover_color="#c53030", text_color=CARD_WHITE, command=self.request_cancel_test)
        btn_yes.place(relx=0.7, rely=0.75, anchor="center")

    def show_cancel_confirmation(self):
        self.cancel_modal.place(relx=0.5, rely=0.5, anchor="center")
        self.cancel_modal.lift()

    def hide_cancel_confirmation(self):
        self.cancel_modal.place_forget()

    def request_cancel_test(self):
        self.hide_cancel_confirmation()
        self.total_seconds_remaining = 0
        self.switch_screen('menu')

    # -----------------------------------------
    # 5. FINISH SCREEN
    # -----------------------------------------
    def build_finish_screen(self):
        self.frame_finish = ctk.CTkFrame(self.screens_frame, fg_color=SUCCESS_GREEN)
        
        self.frame_finish.bind("<Button-1>", lambda e: self.switch_screen('menu'))
        
        center_frame = ctk.CTkFrame(self.frame_finish, fg_color="transparent")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")
        center_frame.bind("<Button-1>", lambda e: self.switch_screen('menu'))
        
        lbl_title = ctk.CTkLabel(center_frame, text="ซักผ้าเสร็จสมบูรณ์", font=("Arial", 70, "bold"), text_color=CARD_WHITE)
        lbl_title.pack(pady=(20, 10))
        lbl_title.bind("<Button-1>", lambda e: self.switch_screen('menu'))
        
        lbl_sub1 = ctk.CTkLabel(center_frame, text="กรุณานำผ้าออกจากถังซัก\nขอบคุณที่ใช้บริการ WashLover", font=("Arial", 32), text_color=CARD_WHITE)
        lbl_sub1.pack(pady=15)
        lbl_sub1.bind("<Button-1>", lambda e: self.switch_screen('menu'))
        
        lbl_sub2 = ctk.CTkLabel(center_frame, text="[ แตะที่หน้าจอเพื่อกลับเมนูหลัก ]", font=("Arial", 24), text_color="#dcfce7")
        lbl_sub2.pack(pady=(50, 0))
        lbl_sub2.bind("<Button-1>", lambda e: self.switch_screen('menu'))

    # =========================================
    # UI LOGIC & TRANSITIONS
    # =========================================
    def switch_screen(self, screen_name):
        self.current_screen = screen_name
        self.frame_menu.pack_forget()
        self.frame_payment.pack_forget()
        self.frame_reward.pack_forget()
        self.frame_process.pack_forget()
        self.frame_finish.pack_forget()
        self.is_processing_payment = False
        
        if screen_name != 'process' and self.anim_event is not None:
            self.after_cancel(self.anim_event)
            self.anim_event = None
        
        if screen_name == 'menu':
            if hasattr(self, 'lbl_coin_info'):
                self.lbl_coin_info.configure(text=f"เหรียญ : {self.get_reg(31)}")
            self.generate_menu_cards()
            self.frame_menu.pack(fill="both", expand=True)
        elif screen_name == 'payment':
            self.frame_payment.pack(fill="both", expand=True)
        elif screen_name == 'reward':
            self.phone_number = ""
            self.reward_timeout = 15
            self.update_phone_display()
            self.frame_reward.pack(fill="both", expand=True)
        elif screen_name == 'process':
            self.update_sidebar_status()
            self.hide_cancel_confirmation()
            self.frame_process.pack(fill="both", expand=True)
            self.washing_animation_loop()
        elif screen_name == 'finish':
            self.frame_finish.pack(fill="both", expand=True)

    def render_menu(self):
        for card_data in self.menu_cards:
            is_active = (self.selected_mode == card_data['key'])
            
            card_data['frame'].configure(border_color=BTN_BLUE if is_active else CARD_WHITE)
            
            btn_text = "ชำระเงิน" if is_active else "เลือกโปรแกรม"
            btn_color = SUCCESS_GREEN if is_active else BTN_BLUE
            btn_hover = "#16a34a" if is_active else "#1e4e9d"
            
            card_data['btn'].configure(text=btn_text, fg_color=btn_color, hover_color=btn_hover)

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
        
        self.lbl_pay_mode.configure(text=self.job_details.get('name', ''))
        self.lbl_pay_time.configure(text=f"{self.job_details.get('mins', 0)} นาที")
        self.lbl_pay_total_ratio.configure(text=f"{display_current_baht}/{display_required_baht} บาท")
        
        self.lbl_pay_coins.configure(text=f"เหรียญสะสม: {current_coins} / {required_coins} เหรียญ\n(ระบบนับ 1 เหรียญ = 10 บาท)")
        
        if current_coins >= required_coins and required_coins > 0:
            if not self.is_processing_payment:
                self.is_processing_payment = True
                self.switch_screen('reward')

    def add_money_test(self, coin_count):
        new_val = self.get_reg(31) + coin_count
        self.set_reg(31, new_val)
        self.set_reg(37, new_val)
        self.total_coins_recorded += coin_count
        self.coins_in_box += coin_count
        
        if self.current_screen == 'payment':
            self.render_payment()
        elif hasattr(self, 'lbl_coin_info'):
            self.lbl_coin_info.configure(text=f"เหรียญ : {self.get_reg(31)}")

    def update_sidebar_status(self):
        total = max(1, self.job_details.get('mins', 30) * 60)
        
        if self.total_seconds_remaining > total * 0.6:
            current_idx = 0 
        elif self.total_seconds_remaining > total * 0.3:
            current_idx = 1 
        else:
            current_idx = 2 
            
        for i, item in enumerate(self.step_frames):
            if i == current_idx:
                item["frame"].configure(fg_color=BTN_BLUE)
                item["lbl"].configure(text_color=CARD_WHITE)
            else:
                item["frame"].configure(fg_color="#273043")
                item["lbl"].configure(text_color=TEXT_MUTED)

    # =========================================
    # CORE LOGIC (TIMER & ANIMATION)
    # =========================================
    def washing_animation_loop(self):
        if self.current_screen == 'process':
            self.anim_idx = (self.anim_idx + 1) % len(self.anim_frames)
            self.lbl_proc_anim.configure(text=self.anim_frames[self.anim_idx])
            self.anim_event = self.after(500, self.washing_animation_loop)

    def timer_loop(self):
        if self.current_screen == 'reward':
            if self.reward_timeout > 0:
                self.reward_timeout -= 1
                self.lbl_reward_timer.configure(text=f"ระบบจะข้ามอัตโนมัติใน {self.reward_timeout} วินาที")
            else:
                self.start_washing_process()

        elif self.current_screen == 'process' and self.total_seconds_remaining > 0:
            self.total_seconds_remaining -= 1
            
            m = math.ceil(self.total_seconds_remaining / 60) 
            self.lbl_proc_min.configure(text=f"{m}")
            
            total = max(1, self.job_details.get('mins', 30) * 60)
            self.progress_pct = ((total - self.total_seconds_remaining) / total)
            self.progress_bar.set(self.progress_pct)
            
            self.update_sidebar_status()
                    
        elif self.current_screen == 'process' and self.total_seconds_remaining <= 0:
            self.switch_screen('finish')
            self.after(5000, lambda: self.switch_screen('menu'))
            
        self.timer_event = self.after(1000, self.timer_loop)

if __name__ == "__main__":
    app = WashingMachineApp()
    app.mainloop()
