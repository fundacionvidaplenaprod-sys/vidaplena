// Achica una foto del teléfono antes de subirla (lado mayor de 1600 px, JPEG al 82 %): sube más rápido con datos
// móviles y queda bajo el tope de 5 MB del servidor. Si no es una imagen, ya es liviana o el navegador no puede
// achicarla, devuelve el archivo tal cual (el servidor decide si lo acepta).
const LADO_MAXIMO = 1600;
const CALIDAD = 0.82;
const ACHICAR_DESDE = 1024 * 1024; // 1 MB

export async function compressImage(file) {
    if (!file?.type?.startsWith('image/') || file.size <= ACHICAR_DESDE || typeof createImageBitmap !== 'function') {
        return file;
    }
    try {
        const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
        const escala = Math.min(1, LADO_MAXIMO / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(bitmap.width * escala);
        canvas.height = Math.round(bitmap.height * escala);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff'; // un PNG con transparencia no queda con fondo negro en JPEG
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close?.();
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', CALIDAD));
        if (!blob || blob.size >= file.size) return file;
        return new File([blob], `${file.name.replace(/\.[^.]+$/, '')}.jpg`, { type: 'image/jpeg', lastModified: file.lastModified });
    } catch {
        return file;
    }
}
