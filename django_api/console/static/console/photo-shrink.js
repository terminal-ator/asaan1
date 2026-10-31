// Shared by the console product forms and the staff app.
// Phone photos are several MB; shrink them on the device before upload so
// saving is quick on mobile data. Falls back to the original file.
window.shrinkPhoto = async function shrinkPhoto(file, maxSide = 1400, quality = 0.82) {
  try {
    if (!file.type || !file.type.startsWith('image/')) return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= 800 * 1024) { if (bitmap.close) bitmap.close(); return file; }
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    if (bitmap.close) bitmap.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (!blob) return file;
    const name = (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg';
    return new File([blob], name, {type: 'image/jpeg'});
  } catch (error) { return file; }
};
