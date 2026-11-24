import { compressImage } from '../utils/compressImage';

describe('compressImage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('deja tal cual un PDF o una foto que ya es liviana', async () => {
    const pdf = new File(['%PDF'], 'hba1c.pdf', { type: 'application/pdf' });
    const liviana = new File(['jpeg'], 'plumas.jpg', { type: 'image/jpeg' });
    expect(await compressImage(pdf)).toBe(pdf);
    expect(await compressImage(liviana)).toBe(liviana);
  });

  it('achica una foto grande a un JPEG de 1600 px de lado mayor', async () => {
    const grande = new File([new Uint8Array(3 * 1024 * 1024)], 'IMG_0001.png', { type: 'image/png' });
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 4000, height: 3000, close: vi.fn() }));
    const ctx = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: '' };
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((cb) => cb(new Blob(['x'.repeat(1000)], { type: 'image/jpeg' })));

    const out = await compressImage(grande);
    expect([out.name, out.type, out.size]).toEqual(['IMG_0001.jpg', 'image/jpeg', 1000]);
    expect(ctx.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 1600, 1200);
  });

  it('si el navegador no puede leer la foto, la sube como está', async () => {
    const grande = new File([new Uint8Array(2 * 1024 * 1024)], 'IMG_0002.heic', { type: 'image/heic' });
    vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('formato no soportado')));
    expect(await compressImage(grande)).toBe(grande);
  });
});
