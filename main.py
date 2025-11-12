import os
import uuid
import asyncio
from datetime import timedelta
from typing import Optional
import json
import logging
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request, Depends, Header, status
from google.cloud import storage
from yt_dlp import YoutubeDL
from pydantic import BaseModel, HttpUrl

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Aumenta o nível de log para DEBUG para ver mais detalhes

# --- Carregar Variáveis de Ambiente ---
load_dotenv()

# --- Variáveis de Configuração Essenciais ---
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
API_KEY = os.getenv("API_KEY")

if not GCS_BUCKET_NAME:
    logger.critical("GCS_BUCKET_NAME environment variable not set. Application cannot start.")
    raise ValueError("GCS_BUCKET_NAME environment variable not set. Application cannot start.")

if not API_KEY:
    logger.critical("API_KEY environment variable not set. Application cannot start.")
    raise ValueError("API_KEY environment variable not set. Application cannot start.")

# --- Inicialização do FastAPI ---
app = FastAPI(
    title="YouTube Downloader Backend",
    description="API para baixar vídeos do YouTube e fazer upload para o Google Cloud Storage.",
    version="0.1.0",
)

# --- Inicialização do GCS Client ---
storage_client: Optional[storage.Client] = None
bucket: Optional[storage.Bucket] = None

def initialize_gcs_client():
    global storage_client, bucket
    try:
        credentials_file_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        logger.debug(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS env var: {credentials_file_path}")

        credentials_json_string = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

        if credentials_json_string:
            logger.debug("DEBUG: GOOGLE_APPLICATION_CREDENTIALS_JSON env var found, attempting to load as string.")
            
            credentials_json_string = credentials_json_string.strip()
            logger.debug(f"DEBUG: Cleaned GOOGLE_APPLICATION_CREDENTIALS_JSON start (first 100 chars): {credentials_json_string[:100]}...")

            try:
                credentials_info = json.loads(credentials_json_string)

                if "private_key" in credentials_info and isinstance(credentials_info["private_key"], str):
                    original_private_key = credentials_info["private_key"]
                    
                    begin_marker = "-----BEGIN PRIVATE KEY-----"
                    end_marker = "-----END PRIVATE KEY-----"

                    if begin_marker in original_private_key and end_marker in original_private_key:
                        start_index = original_private_key.find(begin_marker) + len(begin_marker)
                        end_index = original_private_key.find(end_marker)
                        
                        if start_index < end_index:
                            raw_key_content = original_private_key[start_index:end_index]
                            cleaned_key_content = raw_key_content.strip().replace(" ", "").replace("\n", "").replace("\r", "")
                            
                            credentials_info["private_key"] = f"{begin_marker}\n{cleaned_key_content}\n{end_marker}"
                            logger.debug("DEBUG: private_key content cleaned and re-formatted for PEM.")
                        else:
                            logger.warning("DEBUG: private_key PEM format markers found but content is empty or malformed. Using original.")
                    else:
                        logger.warning("DEBUG: private_key PEM format markers not found. Using original private_key directly.")
                        credentials_info["private_key"] = original_private_key.strip().replace(" ", "").replace("\n", "").replace("\r", "")

                storage_client = storage.Client.from_service_account_info(credentials_info)
                logger.info("Google Cloud Storage client initialized from GOOGLE_APPLICATION_CREDENTIALS_JSON.")
            except json.JSONDecodeError as e:
                logger.critical(f"Failed to parse GOOGLE_APPLICATION_CREDENTIALS_JSON: {e}", exc_info=True)
                raise RuntimeError(f"Failed to initialize Google Cloud Storage client: {e}")
            except Exception as e:
                logger.critical(f"Failed to initialize Google Cloud Storage client using JSON string: {e}", exc_info=True)
                raise RuntimeError(f"Failed to initialize Google Cloud Storage client: {e}")
        elif credentials_file_path and os.path.exists(credentials_file_path):
            logger.debug(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS env var found and file exists at: {credentials_file_path}")
            storage_client = storage.Client.from_service_account_json(credentials_file_path)
            logger.info(f"Google Cloud Storage client initialized from file: {credentials_file_path}.")
        else:
            logger.warning("No valid Google Cloud credentials (JSON string or file) found. Using default application credentials.")
            storage_client = storage.Client()
            logger.info("Google Cloud Storage client initialized with default credentials.")


        if storage_client:
            if GCS_BUCKET_NAME:
                bucket = storage_client.bucket(GCS_BUCKET_NAME)
                # bucket.exists() é um bom ponto para verificar permissões e existência
                bucket.exists()
                logger.info(f"Google Cloud Storage bucket '{GCS_BUCKET_NAME}' connected and accessible.")
            else:
                logger.critical("GCS_BUCKET_NAME is not set. Cannot connect to bucket.")
                raise ValueError("GCS_BUCKET_NAME is not set, GCS client cannot be fully initialized.")
        else:
            logger.critical("Google Cloud Storage client could not be initialized by any method.")
            raise RuntimeError("Google Cloud Storage client could not be initialized.")

    except Exception as e:
        logger.critical(f"Failed to initialize Google Cloud Storage client: {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize Google Cloud Storage client: {e}")


@app.on_event("startup")
async def startup_event():
    logger.debug("DEBUG: Entering startup_event function.")
    try:
        initialize_gcs_client()
        logger.info("Application startup complete.")
    except RuntimeError as e:
        logger.critical(f"Application failed to start due to critical initialization error: {e}")
        raise e 


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key provided.")
    return True

class DownloadRequest(BaseModel):
    youtube_url: HttpUrl # Usando HttpUrl para validação automática
    output_format: Optional[str] = "mp4"
    quality: Optional[str] = "best"

@app.post("/download", dependencies=[Depends(verify_api_key)])
async def download_youtube_video(request_data: DownloadRequest):
    global bucket

    if not bucket:
        logger.critical("Google Cloud Storage bucket not initialized. Critical backend error.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Backend configuration error: GCS not ready. Restart required.")

    youtube_url = str(request_data.youtube_url) # Converte HttpUrl para string
    output_format = request_data.output_format.lower()
    quality = request_data.quality.lower()

    logger.info(f"Received request: URL={youtube_url}, Format={output_format}, Quality={quality}")

    unique_id = uuid.uuid4()
    download_dir = "/tmp"
    temp_filepath_base = os.path.join(download_dir, str(unique_id))

    ydl_opts = {
        'format': f'{quality}[ext={output_format}]/best',
        'outtmpl': f'{temp_filepath_base}.%(ext)s',
        'merge_output_format': output_format,
        'socket_timeout': 30,
        'restrictfilenames': True,
        'quiet': True,
        'noprogress': True,
        'cachedir': False,
        'no_warnings': True,              
        'allow_unplayable_formats': True,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
    }
    
    if output_format == "mp3":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    actual_downloaded_file_path: Optional[str] = None
    signed_url: Optional[str] = None

    try:
        loop = asyncio.get_event_loop()
        ydl = YoutubeDL(ydl_opts)

        info = await loop.run_in_executor(None, lambda: ydl.extract_info(youtube_url, download=True))

        if info and 'filepath' in info:
            actual_downloaded_file_path = info['filepath']
        else:
            downloaded_files = [
                f for f in os.listdir(download_dir)
                if f.startswith(str(unique_id)) and (f.endswith(f".{output_format}") or (output_format == "mp3" and f.endswith(".mp3")))
            ]
            if downloaded_files:
                actual_downloaded_file_path = os.path.join(download_dir, downloaded_files[0])
            else:
                merged_file_candidate = f"{temp_filepath_base}.{output_format}"
                if os.path.exists(merged_file_candidate):
                     actual_downloaded_file_path = merged_file_candidate
                else:
                    raise Exception("yt-dlp download successful, but could not determine actual file path.")

        if not os.path.exists(actual_downloaded_file_path):
            logger.error(f"Downloaded video file not found on server at {actual_downloaded_file_path} after yt-dlp completed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Downloaded video file not found on server after yt-dlp completed.")

        logger.info(f"File downloaded successfully to: {actual_downloaded_file_path}")

        destination_blob_name = f"youtube_downloads/{unique_id}_{os.path.basename(actual_downloaded_file_path)}"
        blob = bucket.blob(destination_blob_name)

        blob.upload_from_filename(actual_downloaded_file_path)
        logger.info(f"File '{actual_downloaded_file_path}' uploaded to GCS as '{destination_blob_name}'.")

        signed_url = blob.generate_signed_url(expiration=timedelta(hours=1))
        logger.info(f"Generated signed URL for GCS blob: {destination_blob_name}")

        return {"status": "success", "download_url": signed_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing download for {youtube_url}: {e}", exc_info=True)
        # Removido o tratamento específico para "Sign in to confirm you're not a bot"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An internal server error occurred: {e}")
    finally:
        if actual_downloaded_file_path and os.path.exists(actual_downloaded_file_path):
            try:
                os.remove(actual_downloaded_file_path)
                logger.info(f"Cleaned up temporary file: {actual_downloaded_file_path}")
            except OSError as e:
                logger.warning(f"Error removing temporary file {actual_downloaded_file_path}: {e}")
        else:
            for f in os.listdir(download_dir):
                if f.startswith(str(unique_id)):
                    try:
                        os.remove(os.path.join(download_dir, f))
                        logger.info(f"Cleaned up residual temporary file: {f}")
                    except OSError as e:
                        logger.warning(f"Error removing residual temporary file {f}: {e}")

@app.get("/")
async def root():
    return {"message": "Welcome to the YouTube Downloader API! Use /download to get started."}

if __name__ == "__main__":
    import uvicorn
    try:
        initialize_gcs_client()
    except Exception as e:
        logger.error(f"Failed to initialize GCS during local startup: {e}")
    uvicorn.run(app, host="0.0.0.0", port=8000)