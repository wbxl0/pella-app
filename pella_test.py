import os
import time
import imaplib
import email
import re
import requests
from datetime import datetime, timedelta, timezone
from seleniumbase import SB
from loguru import logger

# ==========================================
# 1. TG 通知功能 (保持不变)
# ==========================================
def send_tg_notification(status, message, photo_path=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id): return
    tz_bj = timezone(timedelta(hours=8))
    bj_time = datetime.now(tz_bj).strftime('%Y-%m-%d %H:%M:%S')
    emoji = "✅" if "成功" in status else "❌"
    formatted_msg = f"{emoji} **Pella 自动化续期报告**\n━━━━━━━━━━━━━━━━━━\n👤 **账户**: `{os.environ.get('PELLA_EMAIL')}`\n📡 **状态**: {status}\n📝 **详情**: {message}\n🕒 **北京时间**: `{bj_time}`\n━━━━━━━━━━━━━━━━━━"
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={'chat_id': chat_id, 'caption': formatted_msg, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat_id, 'text': formatted_msg, 'parse_mode': 'Markdown'})
    except Exception as e: logger.error(f"TG通知失败: {e}")

# ==========================================
# 2. Gmail 验证码提取 (保持不变)
# ==========================================
def get_pella_code(mail_address, app_password):
    logger.info("📡 正在连接 Gmail 抓取验证码...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(mail_address, app_password)
        mail.select("inbox")
        for i in range(10):
            status, messages = mail.search(None, '(FROM "Pella" UNSEEN)')
            if status == "OK" and messages[0]:
                latest_msg_id = messages[0].split()[-1]
                status, data = mail.fetch(latest_msg_id, "(RFC822)")
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                content = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            content = part.get_payload(decode=True).decode()
                else:
                    content = msg.get_payload(decode=True).decode()
                code = re.search(r'\b\d{6}\b', content)
                if code:
                    mail.store(latest_msg_id, '+FLAGS', '\\Seen')
                    return code.group()
            time.sleep(10)
        return None
    except Exception as e: return None

# ==========================================
# 3. Pella 自动化流程 (优化时间提取)
# ==========================================
def run_test():
    email_addr = os.environ.get("PELLA_EMAIL")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    target_server_url = "https://www.pella.app/server/2b3bbeef0eeb452299a11e431c3c2d5b"
    renew_url = "https://cuty.io/m4w0wJrEmgEC"
    
    with SB(uc=True, xvfb=True) as sb:
        try:
            # --- 第一阶段: 登录与状态识别 [2026-02-11] ---
            logger.info("正在执行 Step 1: 登录流程")
            sb.uc_open_with_reconnect("https://www.pella.app/login", 10)
            sb.sleep(5)
            sb.uc_gui_click_captcha()
            sb.wait_for_element_visible("#identifier-field", timeout=25)
            for char in email_addr:
                sb.add_text("#identifier-field", char)
                time.sleep(0.1)
            sb.press_keys("#identifier-field", "\n")
            sb.sleep(5)
            auth_code = get_pella_code(email_addr, app_pw)
            if not auth_code: raise Exception("验证码抓取失败")
            sb.type('input[data-input-otp="true"]', auth_code)
            sb.sleep(10)

            # --- 第二阶段: 检查 Pella 状态 [2026-02-11] ---
            logger.info("正在执行 Step 2: 检查 Pella 状态")
            sb.uc_open_with_reconnect(target_server_url, 10)
            sb.sleep(10) 
            
            def get_expiry_time_raw(sb_obj):
                try:
                    # 改进的 JS：遍历所有 div，只抓取包含 'expiring' 关键字的那个容器
                    js_code = """
                    var divs = document.querySelectorAll('div');
                    for (var d of divs) {
                        var txt = d.innerText;
                        if (txt.includes('expiring') && (txt.includes('Day') || txt.includes('Hours') || txt.includes('天'))) {
                            return txt;
                        }
                    }
                    return "未找到时间文本";
                    """
                    raw_text = sb_obj.execute_script(js_code)
                    # 清洗文本
                    clean_text = " ".join(raw_text.split())
                    
                    # 截取核心部分：如果是英文，截取 expiring 之后的内容
                    if "expiring in" in clean_text:
                        return clean_text.split("expiring in")[1].split(".")[0].strip()
                    return clean_text[:60]
                except: return "获取失败"

            expiry_before = get_expiry_time_raw(sb)
            logger.info(f"🕒 初始状态: {expiry_before}")

            # 冷却判断
            target_btn = 'a[href*="tpi.li/FSfV"]'
            if sb.is_element_visible(target_btn):
                if "opacity-50" in sb.get_attribute(target_btn, "class"):
                    send_tg_notification("冷却中 🕒", f"按钮尚在冷却。剩余: {expiry_before}", None)
                    return 

            # --- 第三阶段: 续期网站操作 [2026-02-11] ---
            logger.info(f"正在执行 Step 3: 跳转至续期网站 {renew_url}")
            sb.uc_open_with_reconnect(renew_url, 10)
            sb.sleep(5)
            
            for i in range(5):
                if sb.is_element_visible('button#submit-button[data-ref="first"]'):
                    logger.info("正在点击 Continue (first) 按钮...")
                    sb.js_click('button#submit-button[data-ref="first"]')
                    sb.sleep(3)
                    
                    # 【核心修改点】：在点击 first 之后，执行 simple_bypass.py
                    logger.info("检测到人机验证，正在调用 simple_bypass.py...")
                    os.system("python simple_bypass.py")
                    logger.info("simple_bypass.py 执行完毕，继续后续操作")
                    
                    if len(sb.driver.window_handles) > 1: sb.driver.switch_to.window(sb.driver.window_handles[0])
                    if not sb.is_element_visible('button#submit-button[data-ref="first"]'): break

            sb.sleep(6)
            try:
                cf_iframe = 'iframe[src*="cloudflare"]'
                if sb.is_element_visible(cf_iframe):
                    logger.info("检测到 Cloudflare iframe，正在处理...")
                    sb.switch_to_frame(cf_iframe)
                    sb.click('span.mark') 
                    sb.switch_to_parent_frame()
                    sb.sleep(6)
            except: pass

            captcha_btn = 'button#submit-button[data-ref="captcha"]'
            for i in range(6):
                if sb.is_element_visible(captcha_btn):
                    logger.info("正在点击 I am not a robot (captcha) 按钮...")
                    sb.js_click(captcha_btn)
                    sb.sleep(3)
                    if len(sb.driver.window_handles) > 1:
                        curr = sb.driver.current_window_handle
                        for h in sb.driver.window_handles:
                            if h != curr: sb.driver.switch_to.window(h); sb.driver.close()
                        sb.driver.switch_to.window(sb.driver.window_handles[0])
                    if not sb.is_element_visible(captcha_btn): break

            logger.info("等待计时结束...")
            sb.sleep(18)
            final_btn = 'button#submit-button[data-ref="show"]'
            for i in range(8):
                if sb.is_element_visible(final_btn):
                    logger.info("正在点击最终确认按钮 (show)...")
                    sb.js_click(final_btn)
                    sb.sleep(3)
                    if len(sb.driver.window_handles) > 1:
                        curr = sb.driver.current_window_handle
                        for h in sb.driver.window_handles:
                            if h != curr: sb.driver.switch_to.window(h); sb.driver.close()
                        sb.driver.switch_to.window(sb.driver.window_handles[0])
                    if not sb.is_element_visible(final_btn): break

            # --- 第四阶段: 返回 Pella 验证结果 [2026-02-11] ---
            logger.info("正在执行 Step 4: 回访 Pella 验证结果")
            sb.sleep(5)
            sb.uc_open_with_reconnect(target_server_url, 10)
            sb.sleep(10)
            
            expiry_after = get_expiry_time_raw(sb)
            sb.save_screenshot("pella_final_result.png")
            
            send_tg_notification("续期成功 ✅", f"续期前: {expiry_before}\n续期后: {expiry_after}", "pella_final_result.png")

        except Exception as e:
            logger.error(f"异常报告: {e}")
            sb.save_screenshot("error.png")
            send_tg_notification("流程异常 ❌", f"错误详情: `{str(e)}`", "error.png")
            raise e

if __name__ == "__main__":
    run_test()
