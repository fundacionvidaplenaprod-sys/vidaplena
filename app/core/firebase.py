import firebase_admin
from firebase_admin import credentials, storage
import os

# Nombre de tu archivo de credenciales (el que descargaste)
CREDENTIALS_FILE = "firebase_key.json"

# Nombre de tu Bucket (lo encuentras en la consola de Firebase Storage)
# Usualmente es: "tu-proyecto-id.appspot.com"
BUCKET_NAME = "vidaplenastorage.firebasestorage.app" 

def init_firebase():
    """Inicializa la conexión con Firebase si no está activa."""
    if not firebase_admin._apps:
        if not os.path.exists(CREDENTIALS_FILE):
            print(f"⚠️ ADVERTENCIA: No se encontró {CREDENTIALS_FILE}. La subida fallará.")
            return

        cred = credentials.Certificate(CREDENTIALS_FILE)
        firebase_admin.initialize_app(cred, {
            'storageBucket': BUCKET_NAME
        })
        print("🔥 Firebase Conectado Exitosamente")

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