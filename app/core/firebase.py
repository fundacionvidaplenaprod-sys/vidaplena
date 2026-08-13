import firebase_admin
from firebase_admin import credentials, storage
import os
from typing import Optional
from urllib.parse import unquote, urlparse
from app.core.config import settings

# Nombre de tu archivo de credenciales (el que descargaste)
CREDENTIALS_FILE = "firebase_key.json"

# Nombre de tu Bucket (lo encuentras en la consola de Firebase Storage)
# Usualmente es: "tu-proyecto-id.appspot.com"
BUCKET_NAME = "vidaplenastorage.firebasestorage.app" 

def init_firebase():
    """Inicializa la conexión con Firebase si no está activa."""
    if not firebase_admin._apps:
        if not os.path.exists(CREDENTIALS_FILE):
            print(f"ADVERTENCIA: No se encontró {CREDENTIALS_FILE}. La subida fallará.")
            return

        cred = credentials.Certificate(CREDENTIALS_FILE)
        firebase_admin.initialize_app(cred, {
            'storageBucket': BUCKET_NAME
        })
        
        # EL INTERRUPTOR MÁGICO:
        # Si el config dice que estamos en desarrollo, secuestramos el tráfico hacia localhost
        if getattr(settings, 'ENVIRONMENT', 'prod') == 'dev':
            os.environ["FIREBASE_STORAGE_EMULATOR_HOST"] = "127.0.0.1:9199"
            print("⚠️ MODO SANDBOX: Conectado al Emulador Local de Firebase Storage")
        else:
            print("Firebase Conectado Exitosamente (NUBE DE GOOGLE)")

def upload_file_to_firebase(file_content: bytes, filename: str, content_type: str) -> str:
    """
    Sube un archivo (bytes) a Firebase y devuelve la URL pública.
    """
    bucket = storage.bucket()
    blob = bucket.blob(filename)
    
    # Subir el archivo
    blob.upload_from_string(file_content, content_type=content_type)
    
    # Hacerlo público para obtener una URL permanente
    # (Nota: Esto hace que cualquiera con el link pueda verlo, 
    # pero como usamos UUIDs en el nombre, es difícil de adivinar).
    blob.make_public()

    return blob.public_url

def delete_file_from_firebase(filename: str) -> None:
    """
    Borra un archivo de Firebase Storage.
    """
    bucket = storage.bucket()
    blob = bucket.blob(filename)
    blob.delete()


def storage_path_from_public_url(public_url: str) -> Optional[str]:
    """
    Recupera el path interno del bucket (el mismo que se le pasó a
    upload_file_to_firebase) a partir de la public_url que devuelve. Los
    documentos de pacientes/evaluaciones solo guardan esta URL pública, no
    un storage_path aparte (a diferencia de GalleryPhoto/SiteAsset).
    Retorna None si la URL no corresponde a nuestro bucket.
    """
    if not public_url:
        return None
    try:
        parsed = urlparse(public_url)
    except ValueError:
        return None
    prefix = f"/{BUCKET_NAME}/"
    if not parsed.path.startswith(prefix):
        return None
    return unquote(parsed.path[len(prefix):])


def delete_file_from_firebase_by_url(public_url: str) -> None:
    """
    Borra de Storage el archivo correspondiente a una public_url generada
    por upload_file_to_firebase. Lanza ValueError si la URL no se puede
    mapear a un path del bucket — el llamador decide si ignorar ese caso.
    """
    path = storage_path_from_public_url(public_url)
    if not path:
        raise ValueError(f"No se pudo determinar el path de Storage para la URL: {public_url}")
    delete_file_from_firebase(path)