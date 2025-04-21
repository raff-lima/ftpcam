# type: ignore
import os
import json
import time
import locale
import logging
import asyncio
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler 
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

locale.setlocale(locale.LC_TIME, 'pt_BR.utf8')
load_dotenv()

TOKEN = os.getenv("TOKEN")
group_id_str = os.getenv("GROUP_ID", "{}")
GROUP_ID = json.loads(group_id_str)
TOPIC_IMAGES = int(os.getenv("TOPIC_IMAGES"))
TOPIC_VIDEOS = int(os.getenv("TOPIC_VIDEOS"))
WATCH_PATH = os.getenv("PATH") 

bot = Bot(token=TOKEN)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("monitor.log"),  # Salva logs em arquivo
        logging.StreamHandler()  # Exibe logs no terminal
    ]
)

def get_relative_path(file_path):
    try:
        return file_path.split("/files/", 1)[1]
    except IndexError:
        return file_path

async def send_to_telegram(file_path, topic_id, chat_id):
    try:
        creation_time = os.path.getctime(file_path)
        day_of_week = time.strftime("%A", time.localtime(creation_time))
        date = time.strftime("%d/%m/%Y", time.localtime(creation_time))
        hour_min_sec = time.strftime("%H:%M e %S seg", time.localtime(creation_time))

        caption = f"""<blockquote>{day_of_week.capitalize()}</blockquote>
<blockquote>Data: {date}</blockquote>
<blockquote>Horário: {hour_min_sec}</blockquote>"""

        if topic_id == TOPIC_IMAGES:
            with open(file_path, 'rb') as img:
                await bot.send_photo(chat_id, photo=img, caption=caption, message_thread_id=topic_id, parse_mode="HTML")
        elif topic_id == TOPIC_VIDEOS:
            with open(file_path, 'rb') as vid:
                await bot.send_video(chat_id, video=vid, caption=caption, message_thread_id=topic_id, parse_mode="HTML")

        logging.info(f"✅ Arquivo enviado com sucesso: {file_path}")

    except Exception as e:
        logging.error(f"❌ Erro ao enviar arquivo: {e}")

async def monitor_transfer(file_path, timeout=60):
    try:
        relative_path = get_relative_path(file_path)
        elapsed = 0
        while elapsed < timeout:
            if not os.path.exists(file_path):
                await asyncio.sleep(1)
                elapsed += 1
                continue

            initial_size = os.path.getsize(file_path)
            await asyncio.sleep(2)
            if initial_size == os.path.getsize(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        f.read(1)
                    logging.info(f"📥 Transferência concluída para: {relative_path}")
                    return True
                except OSError:
                    await asyncio.sleep(1)
                    elapsed += 3
                    continue
            else:
                elapsed += 2
        return False 
    except Exception as e:
        logging.error(f"❌ [ERRO monitor_transfer] {e}")
        return False
    
import subprocess
import logging
import os

def convert_video(input_path):
    try:
        relative_path = get_relative_path(input_path)
        logging.info(f"🎥 Convertendo vídeo: {relative_path}")

        result = subprocess.run(
            ["/usr/bin/mkvmerge", "-o", f"{os.path.splitext(input_path)[0]}.mp4", input_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        logging.info(f"✅ Vídeo convertido: {get_relative_path(os.path.splitext(input_path)[0] + '.mp4')}")
        return f"{os.path.splitext(input_path)[0]}.mp4"

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Erro ao converter vídeo: {e.stderr.decode()}")
        return None

    except Exception as e:
        logging.error(f"❌ Erro inesperado ao converter vídeo: {e}")
        return None

class WatcherHandler(FileSystemEventHandler):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        logging.info("👀 Monitoramento inicializado.")

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            relative_path = get_relative_path(file_path)
            logging.info(f"📂 Arquivo detectado: {relative_path}")

            asyncio.run_coroutine_threadsafe(self.process_file(file_path), self.loop)

    async def process_file(self, file_path):
        relative_path = get_relative_path(file_path)
        if await monitor_transfer(file_path):
            try:
                relative_path = file_path.split("/files/", 1)[1]
                category = relative_path.split("/")[0]
            except IndexError:
                logging.error("❌ Caminho inválido para extração de categoria.")
                return

            group_id = GROUP_ID.get(category)
            if not group_id:
                logging.warning(f"⚠️ Categoria '{category}' não encontrada no GROUP_ID.")
                return

            if file_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                await send_to_telegram(file_path, TOPIC_IMAGES, group_id)
            elif file_path.lower().endswith(".h264"):
                converted_path = convert_video(file_path)
                if converted_path:
                    await send_to_telegram(converted_path, TOPIC_VIDEOS, group_id)
        else:
            logging.warning(f"⚠️ Falha ao processar arquivo: {relative_path}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    event_handler = WatcherHandler(loop)
    observer = Observer()
    observer.schedule(event_handler, path=WATCH_PATH, recursive=True)

    logging.info("🚀 Iniciando monitoramento...")
    try:
        observer.start()
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("🛑 Monitoramento interrompido pelo usuário.")
        observer.stop()
        logging.info("✅ Monitoramento finalizado.")
    finally:
        observer.join()
        loop.close()
