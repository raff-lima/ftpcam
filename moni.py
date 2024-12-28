# type: ignore

import os
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
from rich.console import Console
from rich.table import Table
from rich.live import Live

locale.setlocale(locale.LC_TIME, 'pt_BR.utf8')
load_dotenv()

TOKEN = os.getenv("TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
TOPIC_IMAGES = int(os.getenv("TOPIC_IMAGES"))
TOPIC_VIDEOS = int(os.getenv("TOPIC_VIDEOS"))
WATCH_PATH = os.getenv("PATH") 

bot = Bot(token=TOKEN)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Console Rich para saída estilizada
console = Console()
table = Table(title="Status do Processamento", show_lines=True)
table.add_column("Arquivo", justify="left", style="cyan", no_wrap=True)
table.add_column("Status", justify="center", style="green")
status_data = {}

async def send_to_telegram(file_path, topic_id):
    try:
        creation_time = os.path.getctime(file_path)
        day_of_week = time.strftime("%A", time.localtime(creation_time))
        date = time.strftime("%d/%m/%Y", time.localtime(creation_time))
        hour_min_sec = time.strftime("Às: %H:%M e %S segundos", time.localtime(creation_time))

        caption = f"""<blockquote>{day_of_week.capitalize()}</blockquote>
<blockquote>{date}</blockquote>
<blockquote>{hour_min_sec}</blockquote>"""

        if topic_id == TOPIC_IMAGES:
            with open(file_path, 'rb') as img:
                await bot.send_photo(chat_id=GROUP_ID, photo=img, caption=caption, message_thread_id=topic_id, parse_mode="HTML")
        elif topic_id == TOPIC_VIDEOS:
            with open(file_path, 'rb') as vid:
                await bot.send_video(chat_id=GROUP_ID, video=vid, caption=caption, message_thread_id=topic_id, parse_mode="HTML")

        logging.info(f"Arquivo enviado com sucesso: {file_path}")
        status_data[file_path] = "Enviado com sucesso"

    except Exception as e:
        logging.error(f"Erro ao enviar arquivo: {e}")
        status_data[file_path] = f"Erro: {e}"

async def monitor_transfer(file_path):
    try:
        while True:
            initial_size = os.path.getsize(file_path)
            await asyncio.sleep(2)
            if initial_size == os.path.getsize(file_path):
                return True
    except FileNotFoundError:
        return False

def convert_video(input_path):
    try:
        output_path = f"{os.path.splitext(input_path)[0]}.mp4"
        logging.info(f"Convertendo vídeo: {input_path}")

        result = subprocess.run(
            ["/usr/bin/mkvmerge", "-o", output_path, input_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        logging.info(f"Saída do comando: {result.stdout.decode()}")
        if result.stderr:
            logging.error(f"Erro ao converter vídeo: {result.stderr.decode()}")

        logging.info(f"Vídeo convertido: {output_path}")
        return output_path

    except subprocess.CalledProcessError as e:
        logging.error(f"Erro ao converter vídeo: {e.stderr.decode()}")
        return None

    except Exception as e:
        logging.error(f"Erro inesperado ao converter vídeo: {e}")
        return None

class WatcherHandler(FileSystemEventHandler):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            logging.info(f"Novo arquivo detectado: {file_path}")

            asyncio.run_coroutine_threadsafe(self.process_file(file_path), self.loop)

    async def process_file(self, file_path):
        status_data[file_path] = "Verificando transferência"
        if await monitor_transfer(file_path):
            status_data[file_path] = "Processando"
            if file_path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                await send_to_telegram(file_path, TOPIC_IMAGES)
            elif file_path.lower().endswith(".h264"):
                converted_path = convert_video(file_path)
                if converted_path:
                    await send_to_telegram(converted_path, TOPIC_VIDEOS)

async def update_table():
    with Live(table, refresh_per_second=4, console=console) as live:
        while True:
            table.rows.clear()
            for file_path, status in status_data.items():
                table.add_row(file_path, status)
            live.update(table)
            await asyncio.sleep(1)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    event_handler = WatcherHandler(loop)
    observer = Observer()
    observer.schedule(event_handler, path=WATCH_PATH, recursive=True)

    logging.info("Iniciando monitoramento de pasta...")
    try:
        loop.create_task(update_table())
        observer.start()
        loop.run_forever()
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Monitoramento encerrado.")
    finally:
        observer.join()
        loop.close()
