import os
import time
import imaplib
import email
import re
from datetime import datetime, timedelta, timezone
from seleniumbase import SB
from loguru import logger

# ==========================================
# 1. Gmail 验证码提取逻辑 (增强搜索过滤)
# ==========================================
def get_pella_code(mail_address, app_password):
    logger.info(f"📡 正在连接 Gmail (IMAP)... 账户: {mail_address}")
    try:
        # 连接 Gmail 服务器
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(mail_address, app_password)
        mail.select("inbox")

        # 核心逻辑：只搜寻【未读】且发件人为 Pella 的邮件
        # 增加尝试次数，总计等待约 100 秒
        for i in range(10):
            logger.info(f"🔍 正在扫描未读邮件 (第 {i+1}/10 次尝试)...")
            status, messages = mail.search(None, '(FROM "Pella" UNSEEN)')
            
            if status == "OK" and messages[0]:
                # 提取最新的一封未读邮件
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

                # 正则匹配 6 位数字
                code = re.search(r'\b\d{6}\b', content)
                if code:
                    logger.success(f"📩 成功抓取到最新验证码: {code.group()}")
                    # 标记为已读，防止干扰下次运行
                    mail.store(latest_msg_id, '+FLAGS', '\\Seen')
                    return code.group()
            
            time.sleep(10)
        
        logger.error("❌ 超过 100 秒未收到新邮件，请检查 Pella 是否成功发送。")
        return None
    except Exception as e:
        logger.error(f"❌ 邮件读取异常: {e}")
        return None

# ==========================================
# 2. Pella 自动化测试流程 (真人行为模拟)
# ==========================================
def run_test():
    email_addr = os.environ.get("PELLA_EMAIL")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    
    # 开启 uc 模式以绕过 Cloudflare 检测
    with SB(uc=True, xvfb=True) as sb:
        try:
            logger.info("第一步: 访问 Pella 登录页")
            sb.uc_open_with_reconnect("https://www.pella.app/login", 10)
            
            # 强制等待 Cloudflare 渲染并尝试破解挑战
            logger.info("等待 Cloudflare 验证渲染...")
            sb.sleep(8)
            sb.uc_gui_click_captcha()
            sb.sleep(2)

            logger.info(f"第二步: 填入邮箱并提交")
            # 定位邮箱输入框
            sb.wait_for_element_visible("#identifier-field", timeout=25)
            
            # 真人模拟：逐字填入
            for char in email_addr:
                sb.add_text("#identifier-field", char)
                time.sleep(0.1)
            
            sb.sleep(1)
            
            # 优先使用物理回车键提交，这比点击 JS 按钮更难被拦截
            logger.info("执行回车键提交...")
            sb.press_keys("#identifier-field", "\n")
            sb.sleep(5)
            
            # 如果依然在邮箱页，则补加 JS 强力点击
            if sb.is_element_visible("#identifier-field"):
                logger.warning("回车提交未跳转，执行补位点击...")
                sb.js_click('button:contains("Continue")')
            
            # 截图保存，查看是否成功跳转到验证码输入页
            sb.sleep(5)
            sb.save_screenshot("after_submit_check.png")

            logger.info("第三步: 启动 Gmail 抓取进程...")
            auth_code = get_pella_code(email_addr, app_pw)
            
            if not auth_code:
                raise Exception("抓取不到最新验证码，Pella 可能因 IP 风险未发送邮件。")

            logger.info(f"第四步: 尝试填入验证码 {auth_code}")
            # 常见的 OTP 输入框属性定位
            otp_selector = 'input[data-input-otp="true"]'
            
            # 等待验证码框出现
            sb.wait_for_element_visible(otp_selector, timeout=20)
            
            # 填入验证码并保存结果
            sb.type(otp_selector, auth_code)
            sb.sleep(10)
            
            logger.info("第五步: 检查最终结果")
            sb.save_screenshot("final_test_result.png")
            
            if not sb.is_element_present("#identifier-field"):
                logger.success("✅ Pella 登录全流程模拟成功！")
            else:
                logger.error("❌ 仍停留在登录页，请检查 after_submit_check.png 截图。")

        except Exception as e:
            logger.error(f"💥 自动化流程异常: {e}")
            sb.save_screenshot("error_full_stack.png")
            raise e

if __name__ == "__main__":
    run_test()
