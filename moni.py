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

group_id_str = os.getenv("GROUP_ID", "{}")
GROUP_ID = json.loads(group_id_str)
TOPIC_IMAGES = json.loads(os.getenv("TOPIC_IMAGES", "{}"))
TOPIC_VIDEOS = json.loads(os.getenv("TOPIC_VIDEOS", "{}"))
WATCH_PATH = os.getenv("PATH") 

CATEGORY_TOKENS = {
    "dores": os.getenv("TOKEN_BOT1"),
    "jonas": os.getenv("TOKEN_BOT2"),
    "ducarmo": os.getenv("TOKEN_BOT3"),
}

BOTS = {cat: Bot(token=token) for cat, token in CATEGORY_TOKENS.items() if token}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("monitor.log"),
        logging.StreamHandler()
    ]
)

def get_relative_path(file_path):
    try:
        return file_path.split("/files/", 1)[1]
    except IndexError:
        return file_path

async def send_to_telegram(file_path, topic_id, chat_id, bot, category):
    try:
        creation_time = os.path.getctime(file_path)
        day_of_week = time.strftime("%A", time.localtime(creation_time))
        date = time.strftime("%d/%m/%Y", time.localtime(creation_time))
        hour_min_sec = time.strftime("%H:%M e %S seg", time.localtime(creation_time))

        caption = f"""<blockquote>{day_of_week.capitalize()}</blockquote>
<blockquote>Data: {date}</blockquote>
<blockquote>Horário: {hour_min_sec}</blockquote>"""

        if topic_id == TOPIC_IMAGES.get(category):
            with open(file_path, 'rb') as img:
                await bot.send_photo(chat_id, photo=img, caption=caption, message_thread_id=topic_id, parse_mode="HTML")
        elif topic_id == TOPIC_VIDEOS.get(category):
            with open(file_path, 'rb') as vid:
                await bot.send_video(chat_id, video=vid, caption=caption, message_thread_id=topic_id, parse_mode="HTML")

        logging.info(f"✅ Arquivo enviado com sucesso: {file_path}")

    except Exception as e:
        logging.error(f"❌ Erro ao enviar arquivo: {e}")
        
from PIL import Image

async def monitor_transfer(file_path, timeout=60):
    try:
        relative_path = get_relative_path(file_path)
        start_time = time.time()
        last_size = -1
        stable_checks = 0
        check_interval = 0.5

        while time.time() - start_time < timeout:
            if not os.path.exists(file_path):
                await asyncio.sleep(check_interval)
                continue

            current_size = os.path.getsize(file_path)

            if current_size == last_size and current_size > 0:
                stable_checks += 1
                if stable_checks >= 3:
                    try:
                        with open(file_path, 'rb') as f:
                            f.read(1)  # tenta acessar
                        # Verifica se é imagem válida
                        if file_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                            try:
                                with Image.open(file_path) as img:
                                    img.verify()  # Confirma que não está corrompida
                            except Exception:
                                logging.warning(f"⚠️ Imagem ainda incompleta ou corrompida: {relative_path}")
                                await asyncio.sleep(1)
                                continue

                        logging.info(f"📥 Transferência concluída para: {relative_path}")
                        return True

                    except OSError:
                        logging.info(f"🔄 Aguardando liberação do arquivo: {relative_path}")
            else:
                stable_checks = 0

            last_size = current_size
            await asyncio.sleep(check_interval)

        logging.warning(f"⏱️ Timeout aguardando transferência: {relative_path}")
        return False

    except Exception as e:
        logging.error(f"❌ [ERRO monitor_transfer] {e}")
        return False


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

        subprocess.run(
            ["/usr/bin/ffmpeg", "-i", f"{os.path.splitext(input_path)[0]}.mp4", "-c", "copy", "-movflags", "+faststart", f"{os.path.splitext(input_path)[0]}FFMPEG.mp4"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )


        logging.info(f"✅ Vídeo convertido: {get_relative_path(os.path.splitext(input_path)[0] + '.mp4')}")
        return f"{os.path.splitext(input_path)[0]}FFMPEG.mp4"

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Erro ao converter vídeo: {e.stderr.decode()}")
        return None

    except Exception as e:
        logging.error(f"❌ Erro inesperado ao converter vídeo: {e}")
        return None

class WatcherHandler(FileSystemEventHandler):
    def __init__(self, loop, semaphore):
        super().__init__()
        self.loop = loop
        self.semaphore = semaphore
        logging.info("👀 Monitoramento inicializado.")

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            relative_path = get_relative_path(file_path)
            logging.info(f"📂 Arquivo detectado: {relative_path}")

            asyncio.run_coroutine_threadsafe(self.process_file(file_path), self.loop)

    async def process_file(self, file_path):
        async with self.semaphore:
            relative_path = get_relative_path(file_path)
            if await monitor_transfer(file_path):
                try:
                    relative_path = file_path.split("/files/", 1)[1]
                    category = relative_path.split("/")[0]
                except IndexError:
                    logging.error("❌ Caminho inválido para extração de categoria.")
                    return

                group_id = GROUP_ID.get(category)
                bot = BOTS.get(category)

                if not group_id or not bot:
                    logging.warning(f"⚠️ Categoria '{category}' não configurada corretamente.")
                    return

                if file_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                    await send_to_telegram(file_path, TOPIC_IMAGES.get(category), group_id, bot, category)
                elif file_path.lower().endswith(".h264"):
                    converted_path = convert_video(file_path)
                    if converted_path:
                        await send_to_telegram(converted_path, TOPIC_VIDEOS.get(category), group_id, bot, category)
            else:
                logging.warning(f"⚠️ Falha ao processar arquivo: {relative_path}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    MAX_CONCURRENT_TASKS = 5
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    event_handler = WatcherHandler(loop, semaphore)
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
